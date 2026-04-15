from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import (
    CashSession, CashMovement, PawnContract, PawnItem,
    Investor, InvestorAccount, InvestorMovement, Customer,
)
from core.models_security import UserRole
from core.api.serializers.pawn_contract import PawnContractCreateSerializer
from core.services.contract_numbering import next_pawn_contract_number
from core.services.credit_line_calc import get_applicable_rate
from core.services.mvi_engine import validate_principal_against_mvi

# Fecha de corte: contratos anteriores a esta fecha se tratan como legado
LEGACY_CUTOFF = date(2026, 1, 1)

# Valores placeholder para clientes creados automáticamente durante la carga masiva.
# El dueño puede completar el KYC completo después desde el panel de clientes.
_PLACEHOLDER_BIRTH_DATE = date(1900, 1, 1)
_PLACEHOLDER_PHONE      = "0000000"


def _split_full_name(full_name: str) -> tuple:
    """
    Divide un nombre completo en (first_name, last_name_paternal, last_name_maternal).

    Ejemplos:
      "Juan Perez"           → ("Juan",  "Perez",    "")
      "Juan Perez Garcia"    → ("Juan",  "Perez",    "Garcia")
      "Juan Carlos Mamani V" → ("Juan",  "Carlos",   "Mamani V")
      "Pedro"                → ("Pedro", "S/Apellido","")
    """
    parts = full_name.strip().split()
    if len(parts) == 0:
        return ("Sin nombre", "Sin apellido", "")
    if len(parts) == 1:
        return (parts[0], "Sin apellido", "")
    if len(parts) == 2:
        return (parts[0], parts[1], "")
    # 3 o más palabras: primera = nombre, segunda = ap. paterno, resto = ap. materno
    return (parts[0], parts[1], " ".join(parts[2:]))


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

        # ── 1) Sesión de caja ─────────────────────────────────────────────────
        try:
            cash_session = CashSession.objects.select_related(
                "cash_register", "branch"
            ).get(public_id=serializer.validated_data["cash_session_id"])
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

        # ── 2) Fechas ─────────────────────────────────────────────────────────
        principal  = serializer.validated_data["principal_amount"]
        start_date = serializer.validated_data.get("start_date") or timezone.now().date()
        due_date   = serializer.validated_data.get("due_date") or _calculate_due_date(start_date)

        # Modo legado: contratos históricos 2023-2025
        is_legacy  = start_date < LEGACY_CUTOFF

        # ── 3) Cliente — búsqueda o creación automática ───────────────────────
        #
        # Prioridad:
        #   a) CI existe en BD        → vincula FK, nombre desde registro oficial
        #   b) CI no existe + nombre  → crea Customer placeholder y vincula
        #   c) Sin CI                 → contrato sin FK (solo texto), tasa BRONCE
        #
        # Los clientes creados en modo (b) son placeholders para la carga masiva.
        # El dueño puede completar el KYC (teléfono real, fecha de nacimiento, etc.)
        # desde el panel de Clientes después de la importación.
        customer    = None
        customer_ci = serializer.validated_data.get("customer_ci", "").strip()
        raw_name    = serializer.validated_data.get("customer_full_name", "").strip()

        if customer_ci:
            customer = Customer.objects.filter(ci=customer_ci).first()

            if customer is None and raw_name:
                # ── Crear cliente placeholder ─────────────────────────────────
                first_name, last_paternal, last_maternal = _split_full_name(raw_name)
                customer = Customer.objects.create(
                    ci                  = customer_ci,
                    first_name          = first_name,
                    last_name_paternal  = last_paternal,
                    last_name_maternal  = last_maternal,
                    birth_date          = _PLACEHOLDER_BIRTH_DATE,
                    phone               = _PLACEHOLDER_PHONE,
                    category            = Customer.Category.BRONCE,
                    score               = 50,
                    created_by          = request.user,
                )

        # ── 4) Tasa de interés ────────────────────────────────────────────────
        # Prioridad: campo explícito del serializer > tasa de categoría del cliente
        custom_rate = serializer.validated_data.get("interest_rate_monthly")
        if custom_rate is not None:
            interest_rate = custom_rate
        else:
            interest_rate = get_applicable_rate(customer)

        # ── 5) Validación MVI ─────────────────────────────────────────────────
        # En modo legado se permite LEGACY_ADVISORY (sin bloqueo duro)
        mvi_check = validate_principal_against_mvi(
            principal=principal,
            suggestion=None,
            contract_date=start_date,
        )
        mvi_alert = None
        if mvi_check["status"] not in ("OK", "SOFT_WARNING", "LEGACY_ADVISORY"):
            # Solo HARD_BLOCK corta el flujo (nunca ocurre en is_legacy)
            return Response(
                {
                    "detail": "El monto supera el límite permitido por el MVI.",
                    "mvi":    mvi_check,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if mvi_check["status"] in ("SOFT_WARNING", "LEGACY_ADVISORY"):
            mvi_alert = mvi_check

        # ── 6) Inversionista (opcional) ───────────────────────────────────────
        investor_id = serializer.validated_data.get("investor_id")
        investor    = None
        account     = None
        if investor_id:
            try:
                investor = Investor.objects.get(public_id=investor_id)
            except Investor.DoesNotExist:
                return Response({"detail": "Inversionista no encontrado."}, status=404)

            account = InvestorAccount.objects.select_for_update().get(investor=investor)
            if account.balance < principal:
                return Response(
                    {
                        "detail": "Fondos insuficientes del inversionista.",
                        "available_balance": str(account.balance),
                    },
                    status=400,
                )

        # ── 7) Campos de sincronización ───────────────────────────────────────
        admin_fee            = serializer.validated_data.get("admin_fee", Decimal("0.00"))
        storage_fee          = serializer.validated_data.get("storage_fee", Decimal("0.00"))
        custom_contract_num  = serializer.validated_data.get("custom_contract_number", "")
        # sync_operator_code   = serializer.validated_data.get("sync_operator_code", "")
        sync_operator_code = request.user.username

        # Validar unicidad del número personalizado (modo legado)
        if is_legacy and custom_contract_num:
            if PawnContract.objects.filter(contract_number=custom_contract_num).exists():
                return Response(
                    {"detail": f"El número de contrato '{custom_contract_num}' ya existe."},
                    status=status.HTTP_409_CONFLICT,
                )

        items_data = serializer.validated_data.get("items", [])

        with transaction.atomic():
            # ── Número de contrato ────────────────────────────────────────────
            if is_legacy and custom_contract_num:
                contract_number = custom_contract_num
            else:
                contract_number = next_pawn_contract_number(cash_session.branch)

            # ── Nombre del cliente en el contrato ─────────────────────────────
            # Siempre usamos el full_name del objeto Customer (existente o recién
            # creado). Si no hay customer (sin CI), usamos el texto libre.
            if customer:
                customer_full_name = customer.full_name   # property del modelo
            else:
                customer_full_name = raw_name or serializer.validated_data.get(
                    "customer_full_name", ""
                ).strip()

            # ── Crear contrato ────────────────────────────────────────────────
            contract = PawnContract.objects.create(
                contract_number       = contract_number,
                branch                = cash_session.branch,
                created_by            = request.user,
                customer              = customer,
                customer_full_name    = customer_full_name,
                customer_ci           = customer_ci,
                principal_amount      = principal,
                interest_rate_monthly = interest_rate,
                start_date            = start_date,
                due_date              = due_date,
                interest_mode         = serializer.validated_data.get("interest_mode", "FIXED"),
                promo_note            = serializer.validated_data.get("promo_note", ""),
                disbursed_cash_session = cash_session,
                interest_accrued_until = start_date,
                admin_fee             = admin_fee,
                storage_fee           = storage_fee,
                sync_operator_code    = sync_operator_code,
                investor              = investor,
            )

            # ── Items empeñados ───────────────────────────────────────────────
            for item in items_data:
                PawnItem.objects.create(
                    contract    = contract,
                    category    = item["category"],
                    description = item.get("description", ""),
                    attributes  = item.get("attributes", {}),
                    has_box     = item.get("has_box", False),
                    has_charger = item.get("has_charger", False),
                    condition   = item.get("condition", "GOOD"),
                    observations = item.get("condition_notes", ""),
                )

            # ── Movimiento de caja (desembolso) ───────────────────────────────
            # En modo legado se marca con effective_date = start_date para que
            # el saldo histórico de caja sea correcto.
            CashMovement.objects.create(
                cash_session   = cash_session,
                cash_register  = cash_session.cash_register,
                branch         = cash_session.branch,
                movement_type  = CashMovement.MovementType.LOAN_OUT,
                amount         = -principal,
                performed_by   = request.user,
                note           = f"Desembolso contrato {contract.contract_number}",
                effective_date = start_date if is_legacy else None,
            )

            # ── Gastos administrativos / almacenaje → entrada de caja ─────────
            extra_fees = (admin_fee or Decimal("0.00")) + (storage_fee or Decimal("0.00"))
            if extra_fees > 0:
                CashMovement.objects.create(
                    cash_session   = cash_session,
                    cash_register  = cash_session.cash_register,
                    branch         = cash_session.branch,
                    movement_type  = CashMovement.MovementType.PAYMENT_IN,
                    amount         = extra_fees,
                    performed_by   = request.user,
                    note           = f"Gastos administrativos/almacenaje contrato {contract.contract_number}",
                    effective_date = start_date if is_legacy else None,
                )

            # ── Inversionista ─────────────────────────────────────────────────
            if investor and account:
                account.balance -= principal
                account.save(update_fields=["balance"])

                InvestorMovement.objects.create(
                    investor         = investor,
                    amount           = principal,
                    movement_type    = InvestorMovement.MovementType.ASSIGN,
                    related_contract = contract,
                    note             = f"Asignado a contrato {contract.contract_number}",
                )

        response_data = {
            "pawn_contract_id":      str(contract.public_id),
            "contract_number":       contract.contract_number,
            "status":                contract.status,
            "principal_amount":      str(contract.principal_amount),
            "interest_rate_monthly": str(contract.interest_rate_monthly),
            "start_date":            str(contract.start_date),
            "due_date":              str(contract.due_date),
            "is_legacy":             is_legacy,
        }

        if mvi_alert:
            response_data["mvi_alert"] = mvi_alert

        return Response(response_data, status=status.HTTP_201_CREATED)
