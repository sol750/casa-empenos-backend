from django.db import transaction
from django.db.models import Sum
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister, CashSession, CashMovement
from core.models_security import UserRole
from core.api.serializers.transfer import TransferCreateSerializer


class TransferCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        roles = set(UserRole.objects.filter(user=request.user).values_list("role__code", flat=True))
        if "OWNER_ADMIN" not in roles:
            return Response({"detail": "Solo OWNER_ADMIN puede transferir fondos."}, status=status.HTTP_403_FORBIDDEN)

        from_cr = CashRegister.objects.select_related("branch").get(
            public_id=serializer.validated_data["from_cash_register_id"]
        )
        to_cr = CashRegister.objects.select_related("branch").get(
            public_id=serializer.validated_data["to_cash_register_id"]
        )

        if from_cr.public_id == to_cr.public_id:
            return Response({"detail": "La caja origen y destino no pueden ser la misma."}, status=status.HTTP_400_BAD_REQUEST)

        # Requiere sesiones abiertas en ambas cajas
        from_session = CashSession.objects.filter(cash_register=from_cr, status=CashSession.Status.OPEN).first()
        to_session = CashSession.objects.filter(cash_register=to_cr, status=CashSession.Status.OPEN).first()

        if not from_session:
            return Response({"detail": "La caja origen no tiene sesión abierta."}, status=status.HTTP_409_CONFLICT)
        if not to_session:
            return Response({"detail": "La caja destino no tiene sesión abierta."}, status=status.HTTP_409_CONFLICT)

        amount = serializer.validated_data["amount"]
        note = serializer.validated_data["note"]

        # Validar fondos suficientes en origen
        mov_total = from_session.movements.aggregate(total=Sum("amount"))["total"] or 0
        expected_from = from_session.opening_amount + mov_total
        if expected_from < amount:
            return Response(
                {"detail": "Fondos insuficientes en caja origen.", "expected_balance": str(expected_from)},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            # Salida (negativo)
            CashMovement.objects.create(
                cash_session=from_session,
                cash_register=from_cr,
                branch=from_cr.branch,
                movement_type=CashMovement.MovementType.TRANSFER_OUT,
                amount=-amount,
                performed_by=request.user,
                note=note,
            )
            # Entrada (positivo)
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
