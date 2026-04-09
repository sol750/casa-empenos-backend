"""
Calculadora de Línea de Crédito VIP
=====================================
Determina cuánto puede empeñar un cliente y a qué tasa,
combinando su categoría (BRONCE/PLATA/ORO) con su score actual
y la deuda activa pendiente.

Además integra la política de descuento de tasa para clientes ORO:
  Si el cliente es ORO → se aplica un descuento de 0.5% sobre la tasa base.
  La tasa mínima nunca baja del 5.00% mensual.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Customer

# ── Parámetros por categoría ───────────────────────────────────────────────────
CATEGORY_CONFIG: dict[str, dict] = {
    "BRONCE": {
        "base_rate":    Decimal("10.00"),
        "max_principal": Decimal("1_500.00"),
    },
    "PLATA": {
        "base_rate":    Decimal("8.00"),
        "max_principal": Decimal("8_000.00"),
    },
    "ORO": {
        "base_rate":    Decimal("7.00"),
        "max_principal": Decimal("20_000.00"),
    },
}

# Descuento exclusivo ORO (sobre la tasa base de la política de monto)
ORO_RATE_DISCOUNT   = Decimal("0.50")
MIN_ALLOWED_RATE    = Decimal("5.00")


def calculate_credit_line(customer: "Customer") -> dict:
    """
    Calcula la línea de crédito disponible de un cliente en este momento.

    Retorna:
        max_amount          – Máximo que puede pedir (ajustado por score)
        active_debt         – Capital vigente en contratos ACTIVE
        available_amount    – max_amount - active_debt (mínimo 0)
        interest_rate_monthly – Tasa aplicable a un nuevo contrato
        category            – Categoría actual del cliente
        score               – Score actual
    """
    from django.db.models import Sum
    from core.models import PawnContract

    config = CATEGORY_CONFIG[customer.category]

    # Factor de score: score 50 → 75 % del máximo; score 100 → 100 %
    # Fórmula: factor = 0.5 + (score / 100) * 0.5
    score_dec    = Decimal(str(max(0, min(100, customer.score))))
    score_factor = Decimal("0.5") + (score_dec / Decimal("100")) * Decimal("0.5")
    max_amount   = (config["max_principal"] * score_factor).quantize(Decimal("0.01"))

    # Deuda activa existente
    active_debt = (
        PawnContract.objects
        .filter(customer=customer, status=PawnContract.Status.ACTIVE)
        .aggregate(total=Sum("principal_amount"))["total"]
    ) or Decimal("0.00")

    available = max(Decimal("0.00"), max_amount - active_debt)

    # Tasa aplicable (sin considerar aún el monto específico del nuevo contrato)
    rate = config["base_rate"]
    if customer.category == "ORO":
        rate = max(MIN_ALLOWED_RATE, rate - ORO_RATE_DISCOUNT)

    return {
        "max_amount":             max_amount,
        "active_debt":            active_debt,
        "available_amount":       available,
        "interest_rate_monthly":  rate,
        "category":               customer.category,
        "score":                  customer.score,
        "risk_color":             customer.risk_color,
    }


def get_applicable_rate(customer: "Customer | None", principal: Decimal) -> Decimal:
    """
    Tasa mensual para un nuevo contrato, combinando:
      1. La política base por monto (interest_policy.py)
      2. El descuento ORO si aplica

    Úsalo en PawnContractCreateView para reemplazar la llamada directa
    a interest_rate_monthly_for_principal().
    """
    from core.services.interest_policy import interest_rate_monthly_for_principal

    base_rate = interest_rate_monthly_for_principal(principal)

    if customer is not None and customer.category == "ORO":
        discounted = base_rate - ORO_RATE_DISCOUNT
        return max(MIN_ALLOWED_RATE, discounted)

    return base_rate
