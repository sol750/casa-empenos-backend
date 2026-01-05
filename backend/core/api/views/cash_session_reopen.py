from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.serializers.cash_session_reopen import CashSessionReopenSerializer
from core.models import CashSession, CashMovement
from core.models_security import UserRole


class CashSessionReopenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CashSessionReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cash_session_id = serializer.validated_data["cash_session_id"]
        reason = serializer.validated_data["reason"]

        # 🔐 Permisos estrictos
        roles = set(
            UserRole.objects.filter(user=request.user)
            .values_list("role__code", flat=True)
        )
        if not roles.intersection({"SUPERVISOR", "OWNER_ADMIN"}):
            return Response({"detail": "No tiene permisos para reaperturar."}, status=403)

        with transaction.atomic():
            cash_session = CashSession.objects.select_for_update().get(public_id=cash_session_id)

            if cash_session.status != CashSession.Status.CLOSED:
                return Response({"detail": "Solo se puede reabrir una sesión CERRADA."}, status=409)

            # Tomamos los montos guardados del cierre
            expected = cash_session.closing_expected_amount
            counted = cash_session.closing_counted_amount
            diff = cash_session.closing_diff_amount

            if expected is None or counted is None or diff is None:
                return Response({"detail": "La sesión no tiene datos de cierre para revertir."}, status=409)

            # Si hubo ajuste automático, lo revertimos con asiento inverso
            if diff != 0:
                # Cierre con faltante (diff negativo) => se creó ADJUSTMENT_OUT
                # Revertir => ADJUSTMENT_IN por el mismo monto
                if diff < 0:
                    reverse_type = CashMovement.MovementType.ADJUSTMENT_IN
                    reverse_amount = abs(diff)
                else:
                    reverse_type = CashMovement.MovementType.ADJUSTMENT_OUT
                    reverse_amount = abs(diff)

                CashMovement.objects.create(
                    cash_session=cash_session,
                    cash_register=cash_session.cash_register,
                    branch=cash_session.branch,
                    movement_type=reverse_type,
                    amount=reverse_amount,
                    performed_by=request.user,
                    note=f"Reapertura: reverso de cierre. Motivo: {reason}",
                )

            # Reabrir sesión (limpiar cierre)
            cash_session.status = CashSession.Status.OPEN
            cash_session.closed_at = None
            cash_session.closed_by = None
            cash_session.closing_counted_amount = None
            cash_session.closing_expected_amount = None
            cash_session.closing_diff_amount = None
            cash_session.closing_notes = ""
            cash_session.save()

        return Response(
            {
                "detail": "Sesión reabierta correctamente.",
                "cash_session_id": str(cash_session.public_id),
                "reopened_at": timezone.now().isoformat(),
            },
            status=200,
        )
