"""
Gestión de Capital del Dueño
==============================
El dueño inyecta su capital propio al sistema o retira utilidades.
Todo movimiento queda auditado con tipo CAPITAL_IN / CAPITAL_OUT.

Endpoints:
  POST /api/cash-registers/{id}/capital          — inyectar capital
  POST /api/cash-registers/{id}/capital/withdraw — retirar capital / cobrar utilidades
  GET  /api/cash-registers/{id}/capital/history  — historial de inyecciones y retiros

Flujo típico de primer día:
  1. Dueño abre sesión en "Caja Dueño" (GLOBAL) con opening_amount=0
  2. POST /capital  →  CAPITAL_IN  (dinero entra al sistema)
  3. POST /transfers →  distribuye a cajas de sucursal
  4. Cajeros abren sus sesiones (opening_amount = fondos recibidos)

Flujo de retiro de utilidades (fin de mes):
  1. Dueño abre sesión en "Caja Dueño"
  2. POST /capital/withdraw  →  CAPITAL_OUT  (retira sus ganancias)
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister, CashSession, CashMovement
from core.api.security import require_roles


def _parse_effective_date(raw) -> tuple[date | None, Response | None]:
    """Parsea y valida effective_date. Retorna (date, None) o (None, error_response)."""
    if not raw:
        return None, None
    try:
        eff = date.fromisoformat(str(raw))
    except ValueError:
        return None, Response(
            {"detail": "effective_date debe estar en formato YYYY-MM-DD."}, status=400
        )
    if eff > timezone.now().date():
        return None, Response(
            {"detail": "effective_date no puede ser futura."}, status=400
        )
    return eff, None


CAPITAL_IN_SOURCES = ["EFECTIVO", "BANCO", "TRANSFERENCIA_BANCARIA", "OTRO"]


class CashCapitalView(APIView):
    """
    POST /api/cash-registers/{register_id}/capital
    Inyectar capital propio del dueño a cualquier caja (normalmente GLOBAL).

    Body:
      amount   — monto a inyectar (Decimal > 0)
      source   — origen del dinero: EFECTIVO | BANCO | TRANSFERENCIA_BANCARIA | OTRO
      note     — descripción libre (ej: "Capital inicial apertura del negocio")
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, register_id):
        require_roles(request.user, {"OWNER_ADMIN"})

        try:
            register = CashRegister.objects.select_related("branch").get(
                public_id=register_id, is_active=True
            )
        except CashRegister.DoesNotExist:
            return Response({"detail": "Caja no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        # Validar campos
        try:
            amount = Decimal(str(request.data.get("amount", 0)))
        except Exception:
            return Response({"detail": "'amount' debe ser un número decimal válido."}, status=400)

        if amount <= 0:
            return Response({"detail": "El monto debe ser mayor a 0."}, status=400)

        source = request.data.get("source", "EFECTIVO").upper()
        if source not in CAPITAL_IN_SOURCES:
            return Response(
                {"detail": f"'source' inválido. Opciones: {', '.join(CAPITAL_IN_SOURCES)}"},
                status=400,
            )

        note = request.data.get("note", "").strip() or f"Inyección de capital — origen: {source}"

        effective_date, err = _parse_effective_date(request.data.get("effective_date"))
        if err:
            return err

        # La sesión debe estar abierta para registrar el movimiento
        session = CashSession.objects.filter(
            cash_register=register, status=CashSession.Status.OPEN
        ).first()

        if not session:
            return Response(
                {
                    "detail": (
                        "No hay una sesión abierta en esta caja. "
                        "Abre la sesión primero con POST /api/cash-sessions/open "
                        "y luego inyecta el capital."
                    ),
                    "cash_register_id": str(register.public_id),
                    "register_name":    register.name,
                    "register_type":    register.register_type,
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            movement = CashMovement.objects.create(
                cash_session   = session,
                cash_register  = register,
                branch         = register.branch,
                movement_type  = CashMovement.MovementType.CAPITAL_IN,
                amount         = amount,
                performed_by   = request.user,
                note           = note,
                effective_date = effective_date,
            )

        # Validar umbrales post-inyección
        from core.services.cash_alerts import check_balance_thresholds
        threshold = check_balance_thresholds(session)

        # La inyección nunca se bloquea (el dueño puede necesitar fondear antes
        # de distribuir a sucursales), pero se alerta si supera max_balance.
        alerts = threshold["alerts"]

        return Response(
            {
                "movement_id":   str(movement.public_id),
                "movement_type": movement.movement_type,
                "amount":        str(movement.amount),
                "source":        source,
                "note":          note,
                "performed_at":  movement.performed_at,
                "balance_after": threshold["balance"],
                "min_balance":   threshold["min_balance"],
                "max_balance":   threshold["max_balance"],
                "cash_register": register.name,
                "register_type": register.register_type,
                "alerts":        alerts,
            },
            status=status.HTTP_201_CREATED,
        )


class CashCapitalWithdrawView(APIView):
    """
    POST /api/cash-registers/{register_id}/capital/withdraw
    El dueño retira capital o cobra sus utilidades.

    Body:
      amount  — monto a retirar
      reason  — UTILIDAD | RETIRO_CAPITAL | OTRO
      note    — descripción libre
    """
    permission_classes = [IsAuthenticated]

    WITHDRAW_REASONS = ["UTILIDAD", "RETIRO_CAPITAL", "OTRO"]

    def post(self, request, register_id):
        require_roles(request.user, {"OWNER_ADMIN"})

        try:
            register = CashRegister.objects.select_related("branch").get(
                public_id=register_id, is_active=True
            )
        except CashRegister.DoesNotExist:
            return Response({"detail": "Caja no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        try:
            amount = Decimal(str(request.data.get("amount", 0)))
        except Exception:
            return Response({"detail": "'amount' debe ser un número decimal válido."}, status=400)

        if amount <= 0:
            return Response({"detail": "El monto debe ser mayor a 0."}, status=400)

        reason = request.data.get("reason", "RETIRO_CAPITAL").upper()
        if reason not in self.WITHDRAW_REASONS:
            return Response(
                {"detail": f"'reason' inválido. Opciones: {', '.join(self.WITHDRAW_REASONS)}"},
                status=400,
            )

        note = request.data.get("note", "").strip() or f"Retiro: {reason}"

        effective_date, err = _parse_effective_date(request.data.get("effective_date"))
        if err:
            return err

        session = CashSession.objects.filter(
            cash_register=register, status=CashSession.Status.OPEN
        ).first()

        if not session:
            return Response(
                {"detail": "No hay una sesión abierta en esta caja."},
                status=status.HTTP_409_CONFLICT,
            )

        # Verificar saldo disponible respetando el mínimo operativo de la caja
        from core.services.cash_alerts import check_balance_thresholds
        current = check_balance_thresholds(session)
        balance = Decimal(current["balance"])
        min_balance = Decimal(current["min_balance"])

        # No se puede retirar si el saldo resultante quedaría bajo el mínimo
        # Excepción: cajas GLOBAL/VAULT pueden tener min_balance=0
        balance_after_projected = balance - amount
        if balance_after_projected < min_balance:
            withdrawable = balance - min_balance
            return Response(
                {
                    "detail": (
                        f"El retiro dejaría la caja por debajo del mínimo operativo "
                        f"(Bs.{min_balance:,.2f}). "
                        f"Máximo retirable en este momento: Bs.{max(withdrawable, Decimal('0')):,.2f}."
                    ),
                    "current_balance":   str(balance),
                    "min_balance":       str(min_balance),
                    "requested":         str(amount),
                    "max_withdrawable":  str(max(withdrawable, Decimal("0"))),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount > balance:
            return Response(
                {
                    "detail": f"Saldo insuficiente. Disponible: {balance} Bs.",
                    "available_balance": str(balance),
                    "requested":         str(amount),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            movement = CashMovement.objects.create(
                cash_session   = session,
                cash_register  = register,
                branch         = register.branch,
                movement_type  = CashMovement.MovementType.CAPITAL_OUT,
                amount         = amount,
                performed_by   = request.user,
                note           = note,
                effective_date = effective_date,
            )

        threshold_after = check_balance_thresholds(session)
        balance_after = Decimal(threshold_after["balance"])

        return Response(
            {
                "movement_id":   str(movement.public_id),
                "movement_type": movement.movement_type,
                "amount":        str(movement.amount),
                "reason":        reason,
                "note":          note,
                "min_balance":   str(min_balance),
                "performed_at":  movement.performed_at,
                "balance_before": str(balance),
                "balance_after":  str(balance_after),
            },
            status=status.HTTP_201_CREATED,
        )


class CashCapitalHistoryView(APIView):
    """
    GET /api/cash-registers/{register_id}/capital/history
    Historial de inyecciones y retiros de capital en una caja.
    Útil para auditar cuánto ha puesto y retirado el dueño.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, register_id):
        require_roles(request.user, {"OWNER_ADMIN"})

        try:
            register = CashRegister.objects.get(public_id=register_id)
        except CashRegister.DoesNotExist:
            return Response({"detail": "Caja no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        qs = (
            CashMovement.objects
            .filter(
                cash_register=register,
                movement_type__in=[
                    CashMovement.MovementType.CAPITAL_IN,
                    CashMovement.MovementType.CAPITAL_OUT,
                ],
            )
            .select_related("performed_by")
            .order_by("-performed_at")
        )

        injections = qs.filter(movement_type="CAPITAL_IN").aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0")

        withdrawals = qs.filter(movement_type="CAPITAL_OUT").aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0")

        records = [
            {
                "movement_id":   str(m.public_id),
                "type":          m.movement_type,
                "amount":        str(m.amount),
                "note":          m.note,
                "performed_by":  m.performed_by.get_full_name() or m.performed_by.username,
                "performed_at":  str(m.performed_at),
            }
            for m in qs[:200]
        ]

        return Response({
            "cash_register":    register.name,
            "register_type":    register.register_type,
            "total_injected":   str(injections),
            "total_withdrawn":  str(withdrawals),
            "net_capital":      str(injections - withdrawals),
            "count":            len(records),
            "records":          records,
        })


# ─── Helper ───────────────────────────────────────────────────────────────────
def _get_session_balance(session) -> Decimal:
    """Saldo real de la sesión: apertura + entradas - salidas."""
    from django.db.models import Case, When, F, DecimalField

    result = session.movements.aggregate(
        inflows=Sum(
            Case(
                When(movement_type__endswith="_IN", then=F("amount")),
                default=Decimal("0"),
                output_field=DecimalField(),
            )
        ),
        outflows=Sum(
            Case(
                When(movement_type__endswith="_OUT", then=F("amount")),
                default=Decimal("0"),
                output_field=DecimalField(),
            )
        ),
    )
    inflows  = result["inflows"]  or Decimal("0")
    outflows = result["outflows"] or Decimal("0")
    return session.opening_amount + inflows - outflows
