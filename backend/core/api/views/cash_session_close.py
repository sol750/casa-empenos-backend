from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.serializers.cash_session_close import CashSessionCloseSerializer
from core.models import CashSession, CashMovement
from core.models_security import UserRole


class CashSessionCloseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CashSessionCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cash_session_id = serializer.validated_data["cash_session_id"]
        counted_amount = serializer.validated_data["counted_amount"]
        note = serializer.validated_data.get("note", "")

        # 🔐 Permisos
        roles = set(
            UserRole.objects.filter(user=request.user)
            .values_list("role__code", flat=True)
        )
        if not roles.intersection({"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}):
            return Response({"detail": "No tiene permisos."}, status=403)

        with transaction.atomic():
            # ✅ Ahora sí: select_for_update dentro de la transacción
            cash_session = CashSession.objects.select_for_update().get(
                public_id=cash_session_id,
            )

            if cash_session.status != CashSession.Status.OPEN:
                return Response({"detail": "La sesión no está abierta."}, status=409)

            expected_amount = cash_session.expected_balance
            diff = counted_amount - expected_amount

            # Registrar cierre
            cash_session.status = CashSession.Status.CLOSED
            cash_session.closed_at = timezone.now()
            cash_session.closed_by = request.user
            cash_session.closing_counted_amount = counted_amount
            cash_session.closing_expected_amount = expected_amount
            cash_session.closing_diff_amount = diff
            cash_session.closing_notes = note
            cash_session.save()

            # Ajuste automático si hay diferencia
            if diff != 0:
                CashMovement.objects.create(
                    cash_session=cash_session,
                    cash_register=cash_session.cash_register,
                    branch=cash_session.branch,
                    movement_type=(
                        CashMovement.MovementType.ADJUSTMENT_IN
                        if diff > 0
                        else CashMovement.MovementType.ADJUSTMENT_OUT
                    ),
                    amount=abs(diff),
                    performed_by=request.user,
                    note="Ajuste automático por cierre de caja",
                )

        return Response(
            {
                "detail": "Caja cerrada correctamente.",
                "expected_amount": str(expected_amount),
                "counted_amount": str(counted_amount),
                "difference": str(diff),
                "report_url": f"/api/cash-sessions/{cash_session.public_id}/closing-report.pdf",
            },
            status=200,
        )
