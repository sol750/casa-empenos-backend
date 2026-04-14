from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.serializers.cash_session_close import CashSessionCloseSerializer
from core.models import CashSession, CashMovement
from core.models_security import UserRole
from core.services.cash_alerts import calculate_surplus


class CashSessionCloseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CashSessionCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cash_session_id = serializer.validated_data["cash_session_id"]
        counted_amount  = serializer.validated_data["counted_amount"]
        note            = serializer.validated_data.get("note", "")

        # 🔐 Permisos
        roles = set(
            UserRole.objects.filter(user=request.user)
            .values_list("role__code", flat=True)
        )
        if not roles.intersection({"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}):
            return Response({"detail": "No tiene permisos."}, status=403)

        with transaction.atomic():
            cash_session = CashSession.objects.select_for_update().select_related(
                "cash_register", "branch", "opened_by"
            ).get(public_id=cash_session_id)

            if cash_session.status != CashSession.Status.OPEN:
                return Response({"detail": "La sesión no está abierta."}, status=409)

            # Saldo lógico calculado sobre todos los movimientos de la sesión
            expected_amount = cash_session.expected_balance
            diff = counted_amount - expected_amount

            # ── Registrar cierre ──────────────────────────────────────────────
            cash_session.status                 = CashSession.Status.CLOSED
            cash_session.closed_at              = timezone.now()
            cash_session.closed_by              = request.user
            cash_session.closing_counted_amount = counted_amount
            cash_session.closing_expected_amount= expected_amount
            cash_session.closing_diff_amount    = diff
            cash_session.closing_notes          = note
            cash_session.save()

            # ── Ajuste automático si hay diferencia física ───────────────────
            if diff != 0:
                CashMovement.objects.create(
                    cash_session  = cash_session,
                    cash_register = cash_session.cash_register,
                    branch        = cash_session.branch,
                    movement_type = (
                        CashMovement.MovementType.ADJUSTMENT_IN
                        if diff > 0
                        else CashMovement.MovementType.ADJUSTMENT_OUT
                    ),
                    amount       = abs(diff),
                    performed_by = request.user,
                    note         = "Ajuste automático por cierre de caja",
                )

        # Calcular desglose financiero del turno
        surplus = calculate_surplus(cash_session)

        # ── Balance final de la caja (= lo que queda físicamente) ────────────
        # Es el counted_amount porque es lo que el cajero contó y quedó en caja.
        # Este es el valor de referencia para abrir mañana.
        final_balance = counted_amount

        cash_register = cash_session.cash_register

        return Response(
            {
                "detail": "Caja cerrada correctamente.",

                # ── Resumen del cierre ───────────────────────────────────────
                "session": {
                    "cash_session_id":  str(cash_session.public_id),
                    "cash_register_id": str(cash_register.public_id),
                    "register_name":    cash_register.name,
                    "branch_code":      cash_session.branch.code if cash_session.branch else None,
                    "opened_by":        cash_session.opened_by.username,
                    "closed_by":        request.user.username,
                    "opened_at":        cash_session.opened_at.isoformat(),
                    "closed_at":        cash_session.closed_at.isoformat(),
                },

                # ── Montos del cierre ────────────────────────────────────────
                "amounts": {
                    "opening_amount":   str(cash_session.opening_amount),
                    "expected_amount":  str(expected_amount),   # saldo lógico
                    "counted_amount":   str(counted_amount),    # conteo físico
                    "difference":       str(diff),              # positivo = sobrante, negativo = faltante
                    "difference_label": (
                        "SIN DIFERENCIA" if diff == Decimal("0")
                        else ("SOBRANTE" if diff > 0 else "FALTANTE")
                    ),
                },

                # ── Referencia para apertura del día siguiente ───────────────
                # El cajero debe ingresar este monto al abrir mañana.
                # Si hay diferencia, el sistema ya la registró como ajuste.
                "next_opening": {
                    "reference_amount": str(final_balance),
                    "message": (
                        f"Mañana ingrese Bs.{final_balance:,.2f} como monto de apertura. "
                        f"Es el saldo físico contado al cierre de hoy."
                    ),
                    "min_balance": str(cash_register.min_balance),
                    "max_balance": str(cash_register.max_balance),
                    "below_minimum": final_balance < cash_register.min_balance,
                },

                # ── Desglose financiero del turno ────────────────────────────
                "surplus_breakdown": surplus,

                # ── URL del reporte PDF ──────────────────────────────────────
                "report_url": f"/api/cash-sessions/{cash_session.public_id}/closing-report.pdf",
            },
            status=200,
        )
