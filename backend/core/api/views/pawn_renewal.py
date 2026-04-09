from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PawnContract, PawnRenewal, CashSession, CashMovement
from core.api.serializers.pawn_renewal import PawnRenewalCreateSerializer
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes
from core.services.interest_calc import prorated_interest


class PawnRenewalCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PawnRenewalCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        # 1) Sesión
        try:
            cash_session = CashSession.objects.select_related("cash_register", "branch").get(
                public_id=serializer.validated_data["cash_session_id"]
            )
        except CashSession.DoesNotExist:
            return Response({"detail": "Sesión de caja no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        if cash_session.status != CashSession.Status.OPEN:
            return Response({"detail": "La sesión de caja no está abierta."}, status=status.HTTP_409_CONFLICT)

        # 2) Contrato
        try:
            contract = PawnContract.objects.select_related("branch").get(
                public_id=serializer.validated_data["pawn_contract_id"]
            )
        except PawnContract.DoesNotExist:
            return Response({"detail": "Contrato no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if contract.status != PawnContract.Status.ACTIVE:
            return Response({"detail": "El contrato no está activo."}, status=status.HTTP_409_CONFLICT)

        # 3) Acceso por sucursal (contrato)
        if not is_owner_admin(request.user):
            allowed_codes = get_user_branch_codes(request.user)
            if contract.branch.code not in allowed_codes:
                return Response({"detail": "No tiene acceso a esta sucursal."}, status=status.HTTP_403_FORBIDDEN)

        # 4) Renovación debe registrarse en la misma sucursal del contrato (MVP)
        if (cash_session.branch_id != contract.branch_id) and (not is_owner_admin(request.user)):
            return Response({"detail": "La renovación debe registrarse en la sucursal del contrato."}, status=status.HTTP_403_FORBIDDEN)

        new_due_date = serializer.validated_data["new_due_date"]
        renew_date = serializer.validated_data.get("renew_date", timezone.now().date())
        fee_amount = serializer.validated_data.get("fee_amount", Decimal("0.00"))
        note = serializer.validated_data.get("note", "")

        if new_due_date <= contract.due_date:
            return Response({"detail": "La nueva fecha de vencimiento debe ser mayor a la actual."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # bloquear contrato
            contract = PawnContract.objects.select_for_update().get(pk=contract.pk)

            totals = contract.payments.aggregate(principal_paid=Sum("principal_paid"))
            principal_paid_total = totals["principal_paid"] or Decimal("0.00")
            outstanding_principal = contract.principal_amount - principal_paid_total

            if outstanding_principal <= 0:
                return Response({"detail": "No se puede renovar un contrato sin capital pendiente."}, status=status.HTTP_409_CONFLICT)

            from_date = contract.interest_accrued_until or contract.start_date

            interest_due = prorated_interest(
                principal=outstanding_principal,
                monthly_rate_percent=contract.interest_rate_monthly,
                from_date=from_date,
                to_date=renew_date,
            )

            amount_charged = (interest_due + fee_amount).quantize(Decimal("0.01"))

            PawnRenewal.objects.create(
                contract=contract,
                cash_session=cash_session,
                renewed_by=request.user,
                previous_due_date=contract.due_date,
                new_due_date=new_due_date,
                amount_charged=amount_charged,
                interest_charged=interest_due,
                fee_charged=fee_amount,
                note=note,
            )

            if amount_charged > 0:
                CashMovement.objects.create(
                    cash_session=cash_session,
                    cash_register=cash_session.cash_register,
                    branch=cash_session.branch,
                    movement_type=CashMovement.MovementType.PAYMENT_IN,
                    amount=amount_charged,
                    performed_by=request.user,
                    note=f"Renovación contrato {contract.contract_number}",
                )

            # actualizar contrato
            contract.due_date = new_due_date
            if renew_date > from_date:
                contract.interest_accrued_until = renew_date
            contract.save(update_fields=["due_date", "interest_accrued_until"])

        return Response(
            {
                "detail": "Contrato renovado.",
                "contract_number": contract.contract_number,
                "new_due_date": str(new_due_date),
                "interest_charged": str(interest_due),
                "fee_charged": str(fee_amount),
                "amount_charged": str(amount_charged),
            },
            status=status.HTTP_201_CREATED,
        )

