from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashSession, CashMovement, PawnContract, PawnItem, Investor, InvestorAccount, InvestorMovement, Customer
from core.models_mvi import AppraisalOverride
from core.models_security import UserRole
from core.api.serializers.pawn_contract import PawnContractCreateSerializer
from core.services.contract_numbering import next_pawn_contract_number
from core.services.credit_line_calc import get_applicable_rate
from core.services.scoring_engine import increment_contract_count
from core.services.mvi_engine import get_mvi_suggestion, validate_principal_against_mvi


def _calculate_due_date(start_date):
    return start_date + relativedelta(months=1)


class PawnContractCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PawnContractCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        roles = set(
            UserRole.objects.filter(user=request.user)
            .values_list("role__code", flat=True)
        )

        if not roles.intersection({"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}):
            return Response(
                {"detail": "No tiene permisos para crear contratos."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 🔹 Obtener sesión de caja
        try:
            cash_session = CashSession.objects.select_related("cash_register", "branch").get(
                public_id=serializer.validated_data["cash_session_id"]
            )
        except CashSession.DoesNotExist:
            return Response(
                {"detail": "CashSession no existe."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if cash_session.status != CashSession.Status.OPEN:
            return Response(
                {"detail": "La sesión de caja no está abierta."},
                status=status.HTTP_409_CONFLICT,
            )

        principal = serializer.validated_data["principal_amount"]

        # Extraer start_date aquí para que el bloque MVI pueda detectar modo legado
        start_date = serializer.validated_data.get("start_date", timezone.now().date())

        # ── MVI: validar monto antes de crear el contrato ─────────────────────
        items_data_pre = serializer.validated_data.get("items", [])
        if items_data_pre:
            # Fix #4: evaluar todos los items y sumar recomendaciones
            customer_ci_pre = serializer.validated_data.get("customer_ci", "").strip().upper()
            customer_cat_pre = None
            if customer_ci_pre:
                _cust_pre = Customer.objects.filter(ci=customer_ci_pre).first()
                if _cust_pre:
                    customer_cat_pre = _cust_pre.category

            from decimal import Decimal as D
            total_recommended = D("0")
            total_hard_max    = D("0")
            total_soft_max    = D("0")
            has_suggestion    = False

            for _item in items_data_pre:
                _result = get_mvi_suggestion(
                    category=_item.get("category", "OTHER"),
                    description=_item.get("description", ""),
                    condition=_item.get("condition", "GOOD"),
                    attributes=_item.get("attributes", {}),
                    customer_category=customer_cat_pre,
                )
                if _result.get("suggestion"):
                    s = _result["suggestion"]
                    total_recommended += D(s["recommended"])
                    total_hard_max    += D(s["hard_max_before_block"])
                    total_soft_max    += D(s["max_soft_warning"])
                    has_suggestion = True

            # Construir suggestion sintética para validate_principal_against_mvi
            if has_suggestion:
                mvi_result = {
                    "suggestion": {
                        "recommended":           str(total_recommended),
                        "max_soft_warning":      str(total_soft_max),
                        "hard_max_before_block": str(total_hard_max),
                    },
                    "config_snapshot": _result.get("config_snapshot", {}),
                }
            else:
                mvi_result = {"suggestion": None}

            mvi_check = validate_principal_against_mvi(
                principal, mvi_result, contract_date=start_date
            )

            if mvi_check["status"] == "LEGACY_ADVISORY":
                # Contrato histórico pre-2026: se acepta sin bloqueo ni override
                mvi_alert = mvi_check
            elif mvi_check["status"] == "HARD_BLOCK":
                # Verificar si viene con override aprobado
                override_id = request.data.get("mvi_override_id")
                if override_id:
                    try:
                        override = AppraisalOverride.objects.get(
                            public_id=override_id,
                            status=AppraisalOverride.Status.APPROVED,
                            contract__isnull=True,  # aún no vinculado a contrato
                        )
                    except AppraisalOverride.DoesNotExist:
                        return Response(
                            {
                                "detail": "El override_id no es válido, no está aprobado o ya fue utilizado.",
                                "mvi_status": "HARD_BLOCK",
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
                else:
                    return Response(
                        {
                            "detail": mvi_check["message"],
                            "mvi_status":    "HARD_BLOCK",
                            "recommended":   mvi_check.get("recommended"),
                            "hard_max":      mvi_check.get("hard_max"),
                            "action_required": (
                                "Crea una solicitud en POST /api/mvi/overrides y espera la "
                                "autorización del dueño. Luego reenvía este request con el campo "
                                "'mvi_override_id'."
                            ),
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
            # SOFT_WARNING / LEGACY_ADVISORY: se deja pasar pero se anota en mvi_alert
            if mvi_check["status"] not in ("SOFT_WARNING", "LEGACY_ADVISORY"):
                mvi_alert = None
        else:
            mvi_result  = None
            mvi_alert   = None
            override_id = None

        # ── Vincular cliente por CI (si existe en la BD) ──────────────────────
        customer = None
        customer_ci = serializer.validated_data.get("customer_ci", "").strip().upper()
        if customer_ci:
            customer = Customer.objects.filter(ci=customer_ci).first()

        investor_id = serializer.validated_data.get("investor_id")

        # Validación previa de existencia del inversor (sin lock todavía)
        investor = None
        if investor_id:
            try:
                investor = Investor.objects.get(public_id=investor_id)
            except Investor.DoesNotExist:
                return Response({"detail": "Inversionista no encontrado."}, status=404)

        # Respetar due_date del payload si fue enviado, sino calcular 1 mes
        due_date = serializer.validated_data.get("due_date") or _calculate_due_date(start_date)

        # Tasa: política base + descuento automático si el cliente es ORO
        interest_rate = get_applicable_rate(customer, principal)

        items_data = serializer.validated_data.get("items", [])

        with transaction.atomic():

            # Fix #1: select_for_update DENTRO del atomic para evitar race condition
            account = None
            if investor:
                account = InvestorAccount.objects.select_for_update().get(investor=investor)
                if account.balance < principal:
                    return Response(
                        {
                            "detail": "Fondos insuficientes del inversionista.",
                            "available_balance": str(account.balance)
                        },
                        status=400
                    )

            # Rellenar campos de texto legacy desde el objeto Customer si existe
            customer_full_name = serializer.validated_data["customer_full_name"]
            if customer and not customer_full_name:
                customer_full_name = customer.full_name

            contract = PawnContract.objects.create(
                contract_number       = next_pawn_contract_number(cash_session.branch),
                branch                = cash_session.branch,
                created_by            = request.user,
                customer              = customer,          # FK normalizado
                customer_full_name    = customer_full_name,
                customer_ci           = customer_ci,
                principal_amount      = principal,
                interest_rate_monthly = interest_rate,
                start_date            = start_date,
                due_date              = due_date,
                interest_mode         = serializer.validated_data.get("interest_mode"),
                promo_note            = serializer.validated_data.get("promo_note"),
                disbursed_cash_session= cash_session,
                interest_accrued_until= start_date,
            )

            # Incrementar contador de contratos del cliente (atómico)
            if customer:
                increment_contract_count(customer)
            # ASIGNAR INVERSIONISTA (account ya bloqueado con select_for_update)
            if investor and account:
                contract.investor = investor
                contract.save(update_fields=["investor"])

                account.balance -= principal
                account.save(update_fields=["balance"])

                # registrar movimiento
                InvestorMovement.objects.create(
                    investor=investor,
                    amount=principal,
                    movement_type=InvestorMovement.MovementType.ASSIGN,
                    related_contract=contract,
                    note=f"Asignado a contrato {contract.contract_number}"
                )

            # 🔹 Crear items
            created_items = []
            for item in items_data:
                pawn_item = PawnItem.objects.create(
                    contract=contract,
                    category=item["category"],
                    description=item.get("description", ""),
                    attributes=item.get("attributes", {}),
                    has_box=item.get("has_box", False),
                    has_charger=item.get("has_charger", False),
                    observations=item.get("observations", ""),
                    condition=item.get("condition", "GOOD"),
                    loan_amount=item.get("loan_amount"),
                )
                created_items.append(pawn_item)

            # 🔹 Vincular override MVI aprobado al contrato (si aplica)
            if items_data_pre and override_id:
                try:
                    AppraisalOverride.objects.filter(
                        public_id=override_id
                    ).update(contract=contract)
                except Exception:
                    pass

            # 🔹 Movimiento de caja
            # Todos los amounts se guardan POSITIVOS; la dirección la da movement_type (_IN/_OUT)
            CashMovement.objects.create(
                cash_session=cash_session,
                cash_register=cash_session.cash_register,
                branch=cash_session.branch,
                movement_type=CashMovement.MovementType.LOAN_OUT,
                amount=principal,
                performed_by=request.user,
                note=f"Desembolso contrato {contract.contract_number}",
            )

        # Desglose de artículos con loan_amount individual
        items_detail = []
        for pi in created_items:
            items_detail.append({
                "item_id":     str(pi.public_id),
                "category":    pi.category,
                "description": pi.description,
                "condition":   pi.condition,
                "loan_amount": str(pi.loan_amount) if pi.loan_amount is not None else None,
            })

        response_data = {
            "pawn_contract_id":      str(contract.public_id),
            "contract_number":       contract.contract_number,
            "status":                contract.status,
            "principal_amount":      str(contract.principal_amount),
            "interest_rate_monthly": str(contract.interest_rate_monthly),
            "interest_mode":         contract.interest_mode,
            "promo_note":            contract.promo_note,
            "start_date":            str(contract.start_date),
            "due_date":              str(contract.due_date),
            # Artículos empeñados con desglose individual
            "items":                 items_detail,
            "items_count":           len(items_detail),
            # Info del cliente vinculado
            "customer_linked":       customer is not None,
            "customer_category":     customer.category if customer else None,
            "oro_discount_applied":  (
                customer is not None and customer.category == "ORO"
            ),
        }

        # Adjuntar advertencia MVI si hubo soft warning o modo legado
        if mvi_alert:
            response_data["mvi_warning"] = {
                "status":      mvi_alert["status"],
                "message":     mvi_alert["message"],
                "recommended": mvi_alert.get("recommended"),
                "max_allowed": mvi_alert.get("max_allowed_no_block") or mvi_alert.get("hard_max"),
                "legacy_mode": mvi_alert.get("legacy_mode", False),
            }

        return Response(response_data, status=status.HTTP_201_CREATED)