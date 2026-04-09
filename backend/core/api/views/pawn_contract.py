from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashSession, CashMovement, PawnContract, PawnItem, Investor, InvestorAccount, InvestorMovement, Customer
from core.models_security import UserRole
from core.api.serializers.pawn_contract import PawnContractCreateSerializer
from core.services.contract_numbering import next_pawn_contract_number
from core.services.credit_line_calc import get_applicable_rate
from core.services.scoring_engine import increment_contract_count


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

        # ── Vincular cliente por CI (si existe en la BD) ──────────────────────
        customer = None
        customer_ci = serializer.validated_data.get("customer_ci", "").strip().upper()
        if customer_ci:
            customer = Customer.objects.filter(ci=customer_ci).first()

        investor_id = serializer.validated_data.get("investor_id")

        investor = None
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
                        "available_balance": str(account.balance)
                    },
                    status=400
                )

        start_date = serializer.validated_data.get(
            "start_date", timezone.now().date()
        )

        due_date = _calculate_due_date(start_date)

        # Tasa: política base + descuento automático si el cliente es ORO
        interest_rate = get_applicable_rate(customer, principal)

        items_data = serializer.validated_data.get("items", [])

        with transaction.atomic():

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
            # ASIGNAR INVERSIONISTA
            if investor:
                contract.investor = investor
                contract.save(update_fields=["investor"])

                # descontar saldo
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
            for item in items_data:
                PawnItem.objects.create(
                    contract=contract,
                    category=item["category"],
                    description=item.get("description", ""),
                    attributes=item.get("attributes", {}),
                    has_box=item.get("has_box", False),
                    has_charger=item.get("has_charger", False),
                    observations=item.get("condition_notes", ""),  # 🔥 CLAVE
                )

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

        return Response(
            {
                "pawn_contract_id":      str(contract.public_id),
                "contract_number":       contract.contract_number,
                "status":                contract.status,
                "principal_amount":      str(contract.principal_amount),
                "interest_rate_monthly": str(contract.interest_rate_monthly),
                "start_date":            str(contract.start_date),
                "due_date":              str(contract.due_date),
                # Info del cliente vinculado
                "customer_linked":       customer is not None,
                "customer_category":     customer.category if customer else None,
                "oro_discount_applied":  (
                    customer is not None and customer.category == "ORO"
                ),
            },
            status=status.HTTP_201_CREATED,
        )