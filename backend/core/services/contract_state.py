"""
Máquina de estados de contratos de empeño.
Calcula el estado en tiempo real basándose en la fecha actual y el historial.
"""
from decimal import Decimal

from django.utils import timezone

GRACE_PERIOD_DAYS = 5    # Fallback si Branch no tiene grace_period_days configurado
ELIGIBLE_SALE_DAYS = 90  # 3 meses sin actividad → alerta ELEGIBLE_VENTA


class ContractState:
    ACTIVO          = "ACTIVO"           # Vigente, puede amortizar y recuperar
    VENCIDO         = "VENCIDO"          # Gracia 0-5 días, solo recuperar
    EN_MORA         = "EN_MORA"          # >5 días, recuperar con interés extra
    ELEGIBLE_VENTA  = "ELEGIBLE_VENTA"   # 90+ días sin movimiento, alerta
    EN_VENTA        = "EN_VENTA"         # Dueño autorizó vitrina
    VENDIDO         = "VENDIDO"          # Artículo vendido
    CERRADO         = "CERRADO"          # Recuperado por el cliente
    CANCELADO       = "CANCELADO"        # Anulado


def get_last_activity_date(contract):
    """Fecha del último movimiento del cliente (pago, renovación o amortización)."""
    dates = []

    last_payment = contract.payments.order_by("-paid_at").first()
    if last_payment:
        dates.append(last_payment.paid_at.date())

    last_renewal = contract.renewals.order_by("-renewed_at").first()
    if last_renewal:
        dates.append(last_renewal.renewed_at.date())

    try:
        last_amort = contract.amortizations.order_by("-performed_at").first()
        if last_amort:
            dates.append(last_amort.performed_at.date())
    except Exception:
        pass

    return max(dates) if dates else None


def get_contract_state(contract, today=None) -> str:
    if today is None:
        today = timezone.now().date()  # Fix #2: hora boliviana correcta

    s = contract.status

    if s == "CLOSED":
        return ContractState.CERRADO
    if s == "SOLD":
        return ContractState.VENDIDO
    if s == "EN_VENTA":
        return ContractState.EN_VENTA
    if s == "CANCELLED":
        return ContractState.CANCELADO
    if s == "DEFAULTED":
        # Fix #8: DEFAULTED es EN_MORA — no tratar como ACTIVO
        days_overdue = (today - contract.due_date).days
        last_activity = get_last_activity_date(contract)
        reference = last_activity if last_activity else contract.start_date
        if (today - reference).days >= ELIGIBLE_SALE_DAYS:
            return ContractState.ELEGIBLE_VENTA
        return ContractState.EN_MORA

    # ACTIVE → calcular desde fechas
    days_overdue = (today - contract.due_date).days

    if days_overdue < 0:
        return ContractState.ACTIVO

    # Fix #3: respetar grace_period_days de la sucursal
    grace = getattr(contract.branch, "grace_period_days", GRACE_PERIOD_DAYS)
    if days_overdue <= grace:
        return ContractState.VENCIDO

    last_activity = get_last_activity_date(contract)
    reference = last_activity if last_activity else contract.start_date
    if (today - reference).days >= ELIGIBLE_SALE_DAYS:
        return ContractState.ELEGIBLE_VENTA

    return ContractState.EN_MORA


def calculate_outstanding_principal(contract) -> Decimal:
    from django.db.models import Sum
    totals = contract.payments.aggregate(total=Sum("principal_paid"))
    paid = totals["total"] or Decimal("0.00")
    return contract.principal_amount - paid


def calculate_recovery_amount(contract, today=None) -> dict:
    """
    Calcula el monto total para recuperar el artículo.
    - VENCIDO (gracia): interés congelado al due_date.
    - ACTIVO / EN_MORA: interés prorrateado hasta hoy.
    """
    from core.services.interest_calc import fixed_interest

    if today is None:
        today = timezone.now().date()

    state = get_contract_state(contract, today)
    outstanding = calculate_outstanding_principal(contract)

    # Interés mensual fijo sobre el capital pendiente — sin prorrateo por días
    interest = fixed_interest(outstanding, contract.interest_rate_monthly)

    return {
        "state":                state,
        "outstanding_principal": outstanding,
        "interest_due":         interest,
        "total_to_recover":     outstanding + interest,
        "can_amortize":         state == ContractState.ACTIVO,
        "can_recover":          state in (
            ContractState.ACTIVO,
            ContractState.VENCIDO,
            ContractState.EN_MORA,
            ContractState.ELEGIBLE_VENTA,
            ContractState.EN_VENTA,
        ),
    }
