from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashSession, CashMovement, PawnContract
from core.models_security import UserRole
from core.api.serializers.pawn_contract import PawnContractCreateSerializer
from core.services.contract_numbering import next_pawn_contract_number


class PawnContractCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PawnContractCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        roles = set(UserRole.objects.filter(user=request.user).values_list("role__code", flat=True))
        allowed_roles = {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}
        if not roles.intersection(allowed_roles):
            return Response({"detail": "No tiene permisos para crear contratos."}, status=status.HTTP_403_FORBIDDEN)

        # Sesión de caja
        cash_session = CashSession.objects.select_related("cash_register", "branch").get(
            public_id=serializer.validated_data["cash_session_id"]
        )

        if cash_session.status != CashSession.Status.OPEN:
            return Response({"detail": "La sesión de caja no está abierta."}, status=status.HTTP_409_CONFLICT)

        # Validar acceso a sucursal (si aplica)
        if cash_session.branch_id is not None:
            has_access = request.user.branch_access.filter(branch_id=cash_session.branch_id).exists()
            if not has_access and "OWNER_ADMIN" not in roles:
                return Response({"detail": "No tiene acceso a esta sucursal."}, status=status.HTTP_403_FORBIDDEN)

        principal = serializer.validated_data["principal_amount"]

        with transaction.atomic():
            contract_number = next_pawn_contract_number(cash_session.branch)

            contract = PawnContract.objects.create(
                contract_number=contract_number,
                branch=cash_session.branch,
                created_by=request.user,
                customer_full_name=serializer.validated_data["customer_full_name"],
                customer_ci=serializer.validated_data.get("customer_ci", ""),
                principal_amount=principal,
                interest_rate_monthly=serializer.validated_data.get("interest_rate_monthly", "8.00"),
                start_date=serializer.validated_data.get("start_date", timezone.now().date()),
                due_date=serializer.validated_data["due_date"],
                interest_mode=serializer.validated_data.get("interest_mode", "MONTHLY_PRORATED"),
                promo_note=serializer.validated_data.get("promo_note", ""),
                disbursed_cash_session=cash_session,
                interest_accrued_until=serializer.validated_data.get("start_date", timezone.now().date()),
            )

            # Movimiento de caja: salida por desembolso
            CashMovement.objects.create(
                cash_session=cash_session,
                cash_register=cash_session.cash_register,
                branch=cash_session.branch,
                movement_type=CashMovement.MovementType.LOAN_OUT,
                amount=-principal,
                performed_by=request.user,
                note=f"Desembolso contrato {contract.contract_number}",
            )

        return Response(
            {
                "pawn_contract_id": str(contract.public_id),
                "contract_number": contract.contract_number,
                "status": contract.status,
                "principal_amount": str(contract.principal_amount),
                "cash_session_id": str(cash_session.public_id),
            },
            status=status.HTTP_201_CREATED,
        )
