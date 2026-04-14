from decimal import Decimal


def fixed_interest(principal: Decimal, monthly_rate_percent: Decimal) -> Decimal:
    """
    Interés mensual fijo sobre el capital ORIGINAL.

    Regla de negocio:
      El interés es siempre un mes completo sin importar los días transcurridos.
      Esto refleja exactamente los libros físicos de la casa de empeños:
        Interés = Capital × (Tasa% / 100)

    Ejemplos:
      fixed_interest(1000, 8)    → 80.00
      fixed_interest(500,  7.5)  → 37.50
      fixed_interest(2000, 6)    → 120.00
    """
    interest = principal * (monthly_rate_percent / Decimal("100.00"))
    return interest.quantize(Decimal("0.01"))
