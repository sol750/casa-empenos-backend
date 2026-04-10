from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.models import PawnContract, CashMovement, InvestorMovement, InvestorAccount
from core.api.security import require_roles, is_owner_admin


class PawnContractCancelView(APIView):
    """
    POST /api/pawn-contracts/cancel

    Cancela (anula) un contrato ACTIVO.
    Solo SUPERVISOR y OWNER_ADMIN pueden cancelar.
    Si el contrato tiene inversionista, revierte el movimiento de caja.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        pawn_contract_id = request.data.get("pawn_contract_id")
        reason = request.data.get("reason", "")

        if not pawn_contract_id:
            return Response({"detail": "Se requiere pawn_contract_id."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            contract = PawnContract.objects.select_related(
                "disbursed_cash_session__cash_register", "branch", "investor"
            ).get(public_id=pawn_contract_id)
        except PawnContract.DoesNotExist:
            return Response({"detail": "Contrato no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if contract.status != PawnContract.Status.ACTIVE:
            return Response(
                {"detail": f"Solo se pueden cancelar contratos activos. Estado actual: {contract.status}"},
                status=status.HTTP_409_CONFLICT,
            )

        # No se puede cancelar si ya tiene pagos registrados
        if contract.payments.exists():
            return Response(
                {"detail": "No se puede cancelar un contrato con pagos registrados."},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            # Si tiene inversionista, revertir el descuento de saldo
            if contract.investor:
                account = InvestorAccount.objects.select_for_update().get(investor=contract.investor)
                account.balance += contract.principal_amount
                account.save(update_fields=["balance"])

                InvestorMovement.objects.create(
                    investor=contract.investor,
                    amount=contract.principal_amount,
                    movement_type=InvestorMovement.MovementType.RETURN,
                    related_contract=contract,
                    note=f"Reversión por cancelación de contrato {contract.contract_number}",
                )

            # Marcar contrato como cancelado
            contract.status = PawnContract.Status.CANCELLED
            contract.save(update_fields=["status"])

        return Response(
            {
                "detail": "Contrato cancelado correctamente.",
                "contract_number": contract.contract_number,
                "reason": reason,
            },
            status=status.HTTP_200_OK,
        )
