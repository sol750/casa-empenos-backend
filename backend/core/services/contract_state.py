"""
Máquina de estados de contratos de empeño.
Calcula el estado en tiempo real basándose en la fecha actual y el historial.
"""
from datetime import date
from decimal import Decimal

GRACE_PERIOD_DAYS = 5    # Días 0-5 tras vencimiento: mismo monto, sin amortizar
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

    # Amortizaciones (si existe la tabla)
    try:
        last_amort = contract.amortizations.order_by("-performed_at").first()
        if last_amort:
            dates.append(last_amort.performed_at.date())
    except Exception:
        pass

    return max(dates) if dates else None


def get_contract_state(contract, today=None) -> str:
    if today is None:
        today = date.today()

    s = contract.status

    if s == "CLOSED":
        return ContractState.CERRADO
    if s == "SOLD":
        return ContractState.VENDIDO
    if s == "EN_VENTA":
        return ContractState.EN_VENTA
    if s == "CANCELLED":
        return ContractState.CANCELADO

    # ACTIVE / DEFAULTED (legacy) → calcular desde fechas
    days_overdue = (today - contract.due_date).days

    if days_overdue < 0:
        return ContractState.ACTIVO

    if days_overdue <= GRACE_PERIOD_DAYS:
        return ContractState.VENCIDO

    # Más de 5 días → verificar ELEGIBLE_VENTA (90 días sin actividad)
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
    from core.services.interest_calc import prorated_interest

    if today is None:
        today = date.today()

    state = get_contract_state(contract, today)
    outstanding = calculate_outstanding_principal(contract)
    from_date = contract.interest_accrued_until or contract.start_date

    # Durante el período de gracia el monto queda congelado al due_date
    if state == ContractState.VENCIDO:
        interest_to = contract.due_date
    else:
        interest_to = today

    interest = prorated_interest(
        principal=outstanding,
        monthly_rate_percent=contract.interest_rate_monthly,
        from_date=from_date,
        to_date=interest_to,
    )

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
