from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PawnContract, PawnPayment, CashSession, CashMovement
from core.models_security import UserRole
from core.api.serializers.pawn_payment import PawnPaymentCreateSerializer
from core.services.interest_calc import prorated_interest


class PawnPaymentCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PawnPaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        roles = set(UserRole.objects.filter(user=request.user).values_list("role__code", flat=True))
        allowed_roles = {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}
        if not roles.intersection(allowed_roles):
            return Response({"detail": "No tiene permisos para registrar pagos."}, status=status.HTTP_403_FORBIDDEN)

        contract = PawnContract.objects.get(public_id=serializer.validated_data["pawn_contract_id"])
        cash_session = CashSession.objects.select_related("cash_register", "branch").get(
            public_id=serializer.validated_data["cash_session_id"]
        )

        if cash_session.status != CashSession.Status.OPEN:
            return Response({"detail": "La sesión de caja no está abierta."}, status=status.HTTP_409_CONFLICT)

        # Pago debe realizarse en la misma sucursal del contrato (MVP)
        if cash_session.branch_id != contract.branch_id and "OWNER_ADMIN" not in roles:
            return Response({"detail": "El pago debe registrarse en la sucursal del contrato."}, status=status.HTTP_403_FORBIDDEN)

        payment_amount = serializer.validated_data["amount"]
        payment_date = serializer.validated_data.get("payment_date", timezone.now().date())
        note = serializer.validated_data.get("note", "")

        # 1) Capital pendiente = principal - sum(principal_paid)
        totals = contract.payments.aggregate(
            principal_paid=Sum("principal_paid"),
        )
        principal_paid_total = totals["principal_paid"] or Decimal("0.00")
        outstanding_principal = contract.principal_amount - principal_paid_total
        if outstanding_principal <= 0:
            return Response({"detail": "El contrato ya no tiene capital pendiente."}, status=status.HTTP_409_CONFLICT)

        # 2) Interés devengado desde start_date (MVP simple)
        # Para que sea correcto a futuro, luego guardaremos last_interest_calc_date en contrato.
        interest_due = prorated_interest(
            principal=outstanding_principal,
            monthly_rate_percent=contract.interest_rate_monthly,
            from_date=contract.interest_accrued_until or contract.start_date,to_date=payment_date,
        )

        # 3) Aplicación del pago: primero interés, luego capital
        interest_paid = min(payment_amount, interest_due)
        remaining = payment_amount - interest_paid
        principal_paid = min(remaining, outstanding_principal)
        out_after = outstanding_principal - principal_paid

        with transaction.atomic():
            payment = PawnPayment.objects.create(
                contract=contract,
                cash_session=cash_session,
                paid_by=request.user,
                amount=payment_amount,
                interest_paid=interest_paid,
                principal_paid=principal_paid,
                note=note,
            )

            # Movimiento de caja: entra dinero
            CashMovement.objects.create(
                cash_session=cash_session,
                cash_register=cash_session.cash_register,
                branch=cash_session.branch,
                movement_type=CashMovement.MovementType.PAYMENT_IN,
                amount=payment_amount,
                performed_by=request.user,
                note=f"Pago contrato {contract.contract_number}",
            )
            # Si el capital pendiente queda en 0, cerramos el contrato
            if out_after <= 0:contract.status = PawnContract.Status.CLOSED
            contract.save(update_fields=["status"])

            # Marcamos hasta qué fecha ya quedó “accrued/cobrado” el interés
            if payment_date > (contract.interest_accrued_until or contract.start_date):contract.interest_accrued_until = payment_date
            contract.save(update_fields=["interest_accrued_until"])


        return Response(
            {
                "pawn_payment_id": str(payment.public_id),
                "contract_number": contract.contract_number,
                "amount": str(payment.amount),
                "interest_paid": str(payment.interest_paid),
                "principal_paid": str(payment.principal_paid),
                "outstanding_principal_after": str(outstanding_principal - principal_paid),
            },
            status=status.HTTP_201_CREATED,
        )
