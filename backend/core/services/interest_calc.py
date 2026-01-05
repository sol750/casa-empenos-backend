from datetime import date
from decimal import Decimal


def prorated_interest(principal: Decimal, monthly_rate_percent: Decimal, from_date: date, to_date: date) -> Decimal:
    """
    Interés prorrateado simple por días.
    Base: tasa mensual / 30 días (convención).
    - principal: capital pendiente
    - monthly_rate_percent: ej 8.00
    """
    if to_date <= from_date:
        return Decimal("0.00")

    days = (to_date - from_date).days
    daily_rate = (monthly_rate_percent / Decimal("100.00")) / Decimal("30.00")
    interest = principal * daily_rate * Decimal(days)
    return interest.quantize(Decimal("0.01"))
