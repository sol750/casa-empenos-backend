from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashSession, CashMovement, PawnContract, PawnItem
from core.models_security import UserRole
from core.api.serializers.pawn_contract import PawnContractCreateSerializer
from core.services.contract_numbering import next_pawn_contract_number
from core.services.interest_policy import interest_rate_monthly_for_principal


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

        start_date = serializer.validated_data.get(
            "start_date", timezone.now().date()
        )

        due_date = _calculate_due_date(start_date)

        interest_rate = interest_rate_monthly_for_principal(principal)

        items_data = serializer.validated_data.get("items", [])

        with transaction.atomic():
            contract = PawnContract.objects.create(
                contract_number=next_pawn_contract_number(cash_session.branch),
                branch=cash_session.branch,
                created_by=request.user,
                customer_full_name=serializer.validated_data["customer_full_name"],
                customer_ci=serializer.validated_data.get("customer_ci", ""),
                principal_amount=principal,
                interest_rate_monthly=interest_rate,
                start_date=start_date,
                due_date=due_date,
                interest_mode=serializer.validated_data.get("interest_mode"),
                promo_note=serializer.validated_data.get("promo_note"),
                disbursed_cash_session=cash_session,
                interest_accrued_until=start_date,
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
            CashMovement.objects.create(
                cash_session=cash_session,
                cash_register=cash_session.cash_register,
                branch=cash_session.branch,
                movement_type=CashMovement.MovementType.LOAN_OUT,
                amount=-principal,  # 🔥 negativo correcto
                performed_by=request.user,
                note=f"Desembolso contrato {contract.contract_number}",
            )

        return Response(
            {
                "pawn_contract_id": str(contract.public_id),
                "contract_number": contract.contract_number,
                "status": contract.status,
                "principal_amount": str(contract.principal_amount),
                "interest_rate_monthly": str(contract.interest_rate_monthly),
                "start_date": str(contract.start_date),
                "due_date": str(contract.due_date),
            },
            status=status.HTTP_201_CREATED,
        )