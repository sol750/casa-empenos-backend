"""
Denominaciones de Caja (Matriz de Billetes/Monedas)
====================================================
POST /api/cash-sessions/<session_id>/denomination   → Registrar conteo
GET  /api/cash-sessions/<session_id>/denomination   → Ver conteo(s)

Se usa en DOS momentos:
  1. Apertura (denom_type=OPENING): el cajero cuenta el efectivo antes de abrir
  2. Cierre   (denom_type=CLOSING): el cajero cuenta el efectivo al cerrar

En apertura, el total del conteo DEBE coincidir con el opening_amount enviado.
"""
from decimal import Decimal

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers, status

from core.models import CashSession, CashDenomination
from core.api.security import require_roles
from core.services.cash_alerts import check_balance_thresholds, validate_opening_vs_previous


# ── Serializer inline ─────────────────────────────────────────────────────────
class DenominationSerializer(serializers.Serializer):
    denom_type = serializers.ChoiceField(choices=CashDenomination.DenomType.choices)
    b_200 = serializers.IntegerField(min_value=0, default=0)
    b_100 = serializers.IntegerField(min_value=0, default=0)
    b_50  = serializers.IntegerField(min_value=0, default=0)
    b_20  = serializers.IntegerField(min_value=0, default=0)
    b_10  = serializers.IntegerField(min_value=0, default=0)
    c_5   = serializers.IntegerField(min_value=0, default=0)
    c_2   = serializers.IntegerField(min_value=0, default=0)
    c_1   = serializers.IntegerField(min_value=0, default=0)


class CashDenominationView(APIView):
    """
    GET  → devuelve los conteos registrados para la sesión
    POST → registra un conteo (OPENING o CLOSING)
    """
    permission_classes = [IsAuthenticated]

    def _get_session(self, session_id):
        try:
            return CashSession.objects.select_related(
                "cash_register", "cash_register__branch", "branch"
            ).get(public_id=session_id)
        except CashSession.DoesNotExist:
            return None

    # ── GET ───────────────────────────────────────────────────────────────────
    def get(self, request, session_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        session = self._get_session(session_id)
        if not session:
            return Response({"detail": "Sesión no encontrada."}, status=404)

        denoms = session.denominations.order_by("denom_type")
        return Response({
            "cash_session_id": str(session.public_id),
            "denominations": [
                {"denom_type": d.denom_type, **d.to_dict(), "counted_by": d.counted_by.username}
                for d in denoms
            ],
        })

    # ── POST ──────────────────────────────────────────────────────────────────
    def post(self, request, session_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        session = self._get_session(session_id)
        if not session:
            return Response({"detail": "Sesión no encontrada."}, status=404)

        ser = DenominationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data

        # Calcular total del conteo
        counted_total = (
            Decimal(v["b_200"]) * 200 + Decimal(v["b_100"]) * 100
            + Decimal(v["b_50"]) * 50 + Decimal(v["b_20"]) * 20
            + Decimal(v["b_10"]) * 10 + Decimal(v["c_5"]) * 5
            + Decimal(v["c_2"]) * 2   + Decimal(v["c_1"]) * 1
        )

        alerts = []

        # Validaciones por tipo
        if v["denom_type"] == CashDenomination.DenomType.OPENING:
            # Verificar que la sesión esté abierta
            if session.status != CashSession.Status.OPEN:
                return Response({"detail": "La sesión no está abierta."}, status=409)
            # Comparar con el opening_amount declarado
            diff = counted_total - session.opening_amount
            if diff != Decimal("0.00"):
                alerts.append({
                    "level":   "WARNING",
                    "code":    "OPENING_COUNT_MISMATCH",
                    "message": (
                        f"El conteo físico (Bs.{counted_total:,.2f}) difiere del "
                        f"monto de apertura declarado (Bs.{session.opening_amount:,.2f}). "
                        f"Diferencia: Bs.{diff:,.2f}."
                    ),
                })
            # Validar mínimo operativo
            if counted_total < session.cash_register.min_balance:
                alerts.append({
                    "level": "CRITICAL",
                    "code":  "BELOW_MINIMUM",
                    "message": (
                        f"La caja inicia con Bs.{counted_total:,.2f}, por debajo del "
                        f"mínimo operativo de Bs.{session.cash_register.min_balance:,.2f}. "
                        f"Se requiere fondeo antes de operar."
                    ),
                })
            # Comparar con cierre del día anterior
            opening_check = validate_opening_vs_previous(counted_total, session.cash_register)
            if opening_check["alert"]:
                alerts.append(opening_check["alert"])

        else:  # CLOSING
            if session.status != CashSession.Status.OPEN:
                return Response({"detail": "La sesión no está abierta."}, status=409)
            # Comparar con el saldo esperado
            expected = session.expected_balance
            diff = counted_total - expected
            if diff != Decimal("0.00"):
                alerts.append({
                    "level":    "WARNING",
                    "code":     "CLOSING_COUNT_MISMATCH",
                    "message": (
                        f"Diferencia de cierre. Saldo esperado: Bs.{expected:,.2f} | "
                        f"Conteo físico: Bs.{counted_total:,.2f} | "
                        f"{'Sobrante' if diff > 0 else 'Faltante'}: Bs.{abs(diff):,.2f}."
                    ),
                    "diff": str(diff),
                })

        with transaction.atomic():
            denom, created = CashDenomination.objects.update_or_create(
                cash_session=session,
                denom_type=v["denom_type"],
                defaults={
                    "b_200": v["b_200"], "b_100": v["b_100"],
                    "b_50":  v["b_50"],  "b_20":  v["b_20"], "b_10": v["b_10"],
                    "c_5":   v["c_5"],   "c_2":   v["c_2"],  "c_1":  v["c_1"],
                    "counted_by": request.user,
                },
            )

        return Response({
            "denom_type":    denom.denom_type,
            "counted_total": str(counted_total),
            "detail":        denom.to_dict(),
            "alerts":        alerts,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
