"""
Servicio de Alertas y Umbrales de Caja
=======================================
Centraliza toda la lógica de monitoreo de liquidez:

  check_balance_thresholds(session)  → dict con alertas de mínimo/máximo
  calculate_surplus(session)         → desglose del excedente (utilidad vs capital)
  get_previous_closing(register)     → saldo de cierre del día anterior
  validate_opening_amount(session)   → compara apertura con cierre anterior
"""
from __future__ import annotations
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import CashSession, CashRegister


def check_balance_thresholds(session: "CashSession") -> dict:
    """
    Evalúa el saldo actual de la sesión contra los umbrales min/max
    de la caja. Devuelve un dict con las alertas activas.

    Niveles:
      CRITICAL  → saldo < min_balance  (necesita fondeo urgente)
      WARNING   → saldo > max_balance  (caja saturada, bajar a bóveda)
      OK        → dentro del rango operativo
    """
    balance      = session.expected_balance
    min_bal      = session.cash_register.min_balance
    max_bal      = session.cash_register.max_balance
    alerts       = []
    status_level = "OK"

    if balance < min_bal:
        deficit = min_bal - balance
        alerts.append({
            "level":   "CRITICAL",
            "code":    "BELOW_MINIMUM",
            "message": (
                f"Saldo insuficiente. La caja tiene Bs.{balance:,.2f} "
                f"y el mínimo operativo es Bs.{min_bal:,.2f}. "
                f"Se necesitan Bs.{deficit:,.2f} de fondeo."
            ),
            "deficit": str(deficit),
        })
        status_level = "CRITICAL"

    elif balance > max_bal:
        surplus_total = balance - min_bal          # todo lo que supera el mínimo
        surplus_safe  = balance - max_bal          # lo que supera el máximo (bajar a bóveda)
        alerts.append({
            "level":         "WARNING",
            "code":          "ABOVE_MAXIMUM",
            "message": (
                f"Caja saturada. El saldo Bs.{balance:,.2f} supera el máximo "
                f"de Bs.{max_bal:,.2f}. Se recomienda bajar Bs.{surplus_safe:,.2f} a bóveda."
            ),
            "recommended_vault_transfer": str(surplus_safe),
        })
        status_level = "WARNING"

    return {
        "status":      status_level,
        "balance":     str(balance),
        "min_balance": str(min_bal),
        "max_balance": str(max_bal),
        "alerts":      alerts,
    }


def calculate_surplus(session: "CashSession") -> dict:
    """
    Calcula el excedente al cierre de sesión y lo desglosa en:
      - capital_recovered: principal pagado por clientes
      - profit_earned:     interés cobrado (UC)
      - operating_expenses: gastos (G) + compras directas (CD)
      - net_surplus:       todo lo que supera el opening_amount

    Este desglose es la base para el reporte de cierre y para
    calcular la ganancia por inversionista.
    """
    from django.db.models import Sum
    from core.models import CashMovement, PawnPayment

    movements = session.movements.all()

    def sum_type(*types):
        return (
            movements.filter(movement_type__in=types)
            .aggregate(s=Sum("amount"))["s"]
        ) or Decimal("0.00")

    # Ingresos
    payment_in    = sum_type("PAYMENT_IN")
    transfer_in   = sum_type("TRANSFER_IN", "VAULT_OUT")
    adj_in        = sum_type("ADJUSTMENT_IN")

    # Egresos
    loan_out      = sum_type("LOAN_OUT")
    purchase_out  = sum_type("PURCHASE_OUT")
    expense_out   = sum_type("EXPENSE_OUT")
    transfer_out  = sum_type("TRANSFER_OUT", "VAULT_IN")
    adj_out       = sum_type("ADJUSTMENT_OUT")

    # Separar capital vs utilidad de los pagos recibidos
    payment_stats = (
        session.pawn_payments.aggregate(
            interest_sum=Sum("interest_paid"),
            principal_sum=Sum("principal_paid"),
        )
    )
    profit_earned      = payment_stats["interest_sum"]  or Decimal("0.00")
    capital_recovered  = payment_stats["principal_sum"] or Decimal("0.00")

    net_flow = (payment_in + transfer_in + adj_in) - (loan_out + purchase_out + expense_out + transfer_out + adj_out)
    net_surplus = session.expected_balance - session.opening_amount

    return {
        "opening_amount":     str(session.opening_amount),
        "current_balance":    str(session.expected_balance),
        "net_surplus":        str(net_surplus),
        # Ingresos
        "payment_in":         str(payment_in),
        "capital_recovered":  str(capital_recovered),
        "profit_earned":      str(profit_earned),      # UC
        "transfer_in":        str(transfer_in),
        # Egresos
        "loan_out":           str(loan_out),           # CN
        "purchase_out":       str(purchase_out),       # CD
        "expense_out":        str(expense_out),        # G
        "transfer_out":       str(transfer_out),
        # Recomendación de bóveda
        "recommended_vault_transfer": str(
            max(Decimal("0.00"), session.expected_balance - session.cash_register.min_balance)
        ),
    }


def get_previous_closing_balance(register: "CashRegister") -> Decimal | None:
    """
    Devuelve el closing_counted_amount de la última sesión cerrada
    de esta caja. None si no existe historial.
    """
    from core.models import CashSession
    last = (
        CashSession.objects
        .filter(cash_register=register, status=CashSession.Status.CLOSED)
        .order_by("-closed_at")
        .first()
    )
    if last:
        return last.closing_counted_amount
    return None


def validate_opening_vs_previous(opening_amount: Decimal, register: "CashRegister") -> dict:
    """
    Compara el monto de apertura ingresado por el cajero contra
    el saldo de cierre del día anterior.

    Retorna:
      matched   → bool
      diff      → diferencia (positivo = sobrante, negativo = faltante)
      previous  → saldo de cierre anterior (None si es primera sesión)
      alert     → mensaje de alerta si hay diferencia
    """
    previous = get_previous_closing_balance(register)
    if previous is None:
        return {"matched": True, "diff": "0.00", "previous": None, "alert": None}

    diff = opening_amount - previous
    matched = diff == Decimal("0.00")

    alert = None
    if not matched:
        direction = "sobrante" if diff > 0 else "faltante"
        alert = {
            "level":   "WARNING",
            "code":    "OPENING_MISMATCH",
            "message": (
                f"Diferencia de apertura detectada. "
                f"Cierre anterior: Bs.{previous:,.2f} | "
                f"Apertura ingresada: Bs.{opening_amount:,.2f} | "
                f"{direction.capitalize()}: Bs.{abs(diff):,.2f}. "
                f"Se notificará al supervisor."
            ),
        }

    return {
        "matched":  matched,
        "diff":     str(diff),
        "previous": str(previous),
        "alert":    alert,
    }
