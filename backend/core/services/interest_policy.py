from decimal import Decimal


def interest_rate_monthly_for_principal(principal: Decimal) -> Decimal:
    """
    Regla de negocio (auditable) para tasa mensual según monto.
    - < 1500: 10%
    - 1500..8000: 8%
    - > 8000: 7%
    """
    principal = Decimal(principal)

    if principal < Decimal("1500"):
        return Decimal("10.00")
    if principal > Decimal("8000"):
        return Decimal("7.00")
    return Decimal("8.00")
