"""
DEPRECADO — interest_policy.py
================================
Esta función fue eliminada de la lógica activa.

La tasa ya no depende del monto prestado.
Se usa exclusivamente la jerarquía de categoría de cliente:
  custom_rate_pct > InterestCategoryConfig > CATEGORY_CONFIG default

Ver: core/services/credit_line_calc.py → get_applicable_rate()
"""
from decimal import Decimal


def interest_rate_monthly_for_principal(principal: Decimal) -> Decimal:
    """
    DEPRECADO. No llamar desde código nuevo.
    Mantenido solo para evitar ImportError en tests o migraciones antiguas.
    """
    raise NotImplementedError(
        "interest_rate_monthly_for_principal está deprecada. "
        "Usa get_applicable_rate() de credit_line_calc.py."
    )
