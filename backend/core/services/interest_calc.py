from datetime import date
from decimal import Decimal


def fixed_interest(principal: Decimal, monthly_rate_percent: Decimal) -> Decimal:
    """
    Interés mensual fijo sobre el capital — exactamente 1 mes.

    Fórmula: principal × (monthly_rate_percent / 100)

    Ejemplos:
      fixed_interest(1000, 8)    → 80.00
      fixed_interest(500,  7.5)  → 37.50
      fixed_interest(2000, 6)    → 120.00
    """
    interest = principal * (monthly_rate_percent / Decimal("100.00"))
    return interest.quantize(Decimal("0.01"))


def months_between(from_date: date, to_date: date) -> int:
    """
    Número de meses completos entre dos fechas. Mínimo 1.

    Se usa en la Fase de Sincronización para calcular el interés acumulado
    cuando se registra una transacción histórica con effective_date.

    Ejemplos:
      months_between(date(2024,1,15), date(2024,3,15)) → 2
      months_between(date(2024,1,15), date(2024,2,1))  → 1  (< 1 mes completo → 1)
      months_between(date(2024,1,15), date(2024,1,15)) → 1  (misma fecha → mínimo 1)
    """
    if to_date <= from_date:
        return 1
    months = (to_date.year - from_date.year) * 12 + (to_date.month - from_date.month)
    return max(1, months)


def fixed_interest_for_period(
    principal: Decimal,
    monthly_rate_percent: Decimal,
    from_date: date | None = None,
    to_date: date | None = None,
) -> Decimal:
    """
    Interés fijo para un período que puede abarcar múltiples meses.

    Si from_date y to_date se proveen → multiplica por meses transcurridos.
    Si no → calcula para exactamente 1 mes (equivalente a fixed_interest).

    Uso en sincronización:
      from_date = contract.interest_accrued_until (o start_date)
      to_date   = effective_date del pago/renovación

    Ejemplos:
      fixed_interest_for_period(1000, 8, date(2024,1,1), date(2024,3,1)) → 160.00 (2 meses)
      fixed_interest_for_period(1000, 8)                                  →  80.00 (1 mes)
    """
    n = months_between(from_date, to_date) if (from_date and to_date) else 1
    return (fixed_interest(principal, monthly_rate_percent) * n).quantize(Decimal("0.01"))
