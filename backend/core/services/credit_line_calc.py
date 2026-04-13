"""
Calculadora de Línea de Crédito VIP
=====================================
Determina cuánto puede empeñar un cliente y a qué tasa,
combinando su categoría (BRONCE/PLATA/ORO) con su score actual
y la deuda activa pendiente.

Las tasas base se leen de InterestCategoryConfig (BD) si existen,
con fallback a los defaults hardcoded para garantizar arranque limpio.

Jerarquía de tasa (mayor prioridad primero):
  1. customer.custom_rate_pct (tasa individual)
  2. InterestCategoryConfig[category].base_rate_pct (config en BD)
  3. CATEGORY_CONFIG[category]["base_rate"] (default hardcoded)
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Customer

# ── Defaults hardcoded (fallback si no hay config en BD) ─────────────────────
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

# Descuento exclusivo ORO (sobre la tasa base)
ORO_RATE_DISCOUNT   = Decimal("0.50")
MIN_ALLOWED_RATE    = Decimal("5.00")


def _get_category_config(category: str) -> dict:
    """
    Retorna {base_rate, max_principal} para la categoría dada.
    Lee de InterestCategoryConfig en BD; si no existe usa el default.
    """
    try:
        from core.models import InterestCategoryConfig
        cfg = InterestCategoryConfig.objects.filter(category=category).first()
        if cfg:
            return {"base_rate": cfg.base_rate_pct, "max_principal": cfg.max_principal}
    except Exception:
        pass
    return CATEGORY_CONFIG[category]


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

    config = _get_category_config(customer.category)

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

    # Tasa aplicable: custom_rate del cliente > config categoría
    if getattr(customer, "custom_rate_pct", None) is not None:
        rate = customer.custom_rate_pct
    else:
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
        "custom_rate":            getattr(customer, "custom_rate_pct", None) is not None,
    }


def get_applicable_rate(customer: "Customer | None", principal: Decimal) -> Decimal:
    """
    Tasa mensual para un nuevo contrato.
    Jerarquía: custom_rate > categoría BD > política por monto.
    """
    # 1. Tasa individual del cliente
    if customer is not None and getattr(customer, "custom_rate_pct", None) is not None:
        return customer.custom_rate_pct

    # 2. Tasa por categoría (BD o default)
    if customer is not None:
        config = _get_category_config(customer.category)
        rate = config["base_rate"]
        if customer.category == "ORO":
            rate = max(MIN_ALLOWED_RATE, rate - ORO_RATE_DISCOUNT)
        return rate

    # 3. Política por monto (sin cliente)
    from core.services.interest_policy import interest_rate_monthly_for_principal
    return interest_rate_monthly_for_principal(principal)
