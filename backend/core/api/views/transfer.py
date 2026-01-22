from decimal import Decimal
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister, CashSession, CashMovement
from core.api.serializers.transfer import TransferCreateSerializer
from core.api.security import require_roles


class TransferCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 1) Solo OWNER_ADMIN
        try:
            require_roles(request.user, {"OWNER_ADMIN"})
        except Exception as e:
            return Response({"detail": "Solo OWNER_ADMIN puede transferir fondos."}, status=status.HTTP_403_FORBIDDEN)

        from_id = serializer.validated_data["from_cash_register_id"]
        to_id = serializer.validated_data["to_cash_register_id"]
        amount = serializer.validated_data["amount"]
        note = serializer.validated_data.get("note", "")

        if from_id == to_id:
            return Response(
                {"detail": "La caja origen y destino no pueden ser la misma."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2) Obtener cajas
        try:
            from_cr = CashRegister.objects.select_related("branch").get(public_id=from_id)
            to_cr = CashRegister.objects.select_related("branch").get(public_id=to_id)
        except CashRegister.DoesNotExist:
            return Response({"detail": "Caja no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        # 3) Requiere sesiones abiertas en ambas cajas (con bloqueo)
        with transaction.atomic():
            from_session = (
                CashSession.objects.select_for_update()
                .filter(cash_register=from_cr, status=CashSession.Status.OPEN)
                .first()
            )
            to_session = (
                CashSession.objects.select_for_update()
                .filter(cash_register=to_cr, status=CashSession.Status.OPEN)
                .first()
            )

            if not from_session:
                return Response({"detail": "La caja origen no tiene sesión abierta."}, status=status.HTTP_409_CONFLICT)
            if not to_session:
                return Response({"detail": "La caja destino no tiene sesión abierta."}, status=status.HTTP_409_CONFLICT)

            # 4) Validar fondos en origen usando tu expected_balance (auditable)
            expected_from = from_session.expected_balance
            if expected_from < amount:
                return Response(
                    {"detail": "Fondos insuficientes en caja origen.", "expected_balance": str(expected_from)},
                    status=status.HTTP_409_CONFLICT,
                )

            # 5) Registrar movimientos (convención: IN positivo, OUT negativo)
            amount = Decimal(amount)

            CashMovement.objects.create(
                cash_session=from_session,
                cash_register=from_cr,
                branch=from_cr.branch,
                movement_type=CashMovement.MovementType.TRANSFER_OUT,
                amount=-amount,
                performed_by=request.user,
                note=note,
            )

            CashMovement.objects.create(
                cash_session=to_session,
                cash_register=to_cr,
                branch=to_cr.branch,
                movement_type=CashMovement.MovementType.TRANSFER_IN,
                amount=amount,
                performed_by=request.user,
                note=note,
            )

        return Response(
            {"detail": "Transferencia registrada.", "amount": str(amount)},
            status=status.HTTP_201_CREATED,
        )
