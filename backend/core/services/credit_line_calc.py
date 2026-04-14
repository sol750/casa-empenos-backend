"""
Calculadora de Tasa y Línea de Crédito
=======================================
Determina la tasa sugerida para un cliente según su categoría (ORO/PLATA/BRONCE).

NO hay límite automático de monto. El dueño decide el capital manualmente.
El cajero puede además sobreescribir la tasa en el momento de crear el contrato.

Jerarquía de tasa (mayor prioridad primero):
  1. customer.custom_rate_pct  → tasa individual configurada por el dueño
  2. InterestCategoryConfig[category].base_rate_pct → config en BD
  3. CATEGORY_CONFIG[category]["base_rate"]  → default hardcoded (arranque limpio)
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Customer

# ── Tasas base por categoría (sin límites de monto) ──────────────────────────
CATEGORY_CONFIG: dict[str, dict] = {
    "BRONCE": {"base_rate": Decimal("10.00")},
    "PLATA":  {"base_rate": Decimal("8.00")},
    "ORO":    {"base_rate": Decimal("7.00")},
}

# Descuento exclusivo ORO sobre la tasa base
ORO_RATE_DISCOUNT = Decimal("0.50")
MIN_ALLOWED_RATE  = Decimal("5.00")

# Monto simbólico que representa "sin límite" en dashboards y reportes
UNLIMITED_AMOUNT  = Decimal("999999.00")


def _get_category_config(category: str) -> dict:
    """
    Retorna {"base_rate": Decimal} para la categoría indicada.
    Lee de InterestCategoryConfig en BD; si no existe usa el default.
    """
    try:
        from core.models import InterestCategoryConfig
        cfg = InterestCategoryConfig.objects.filter(category=category).first()
        if cfg:
            return {"base_rate": cfg.base_rate_pct}
    except Exception:
        pass
    return CATEGORY_CONFIG.get(category, CATEGORY_CONFIG["BRONCE"])


def calculate_credit_line(customer: "Customer") -> dict:
    """
    Retorna la tasa sugerida y la deuda activa del cliente.

    No existe max_amount ni score_factor: el dueño fija el capital manualmente.
    available_amount se reporta como UNLIMITED_AMOUNT (999,999.00) para indicar
    al frontend que no hay restricción automática.
    """
    from django.db.models import Sum
    from core.models import PawnContract

    config = _get_category_config(customer.category)

    # Deuda activa en contratos vigentes
    active_debt = (
        PawnContract.objects
        .filter(customer=customer, status=PawnContract.Status.ACTIVE)
        .aggregate(total=Sum("principal_amount"))["total"]
    ) or Decimal("0.00")

    # Tasa sugerida: custom > categoría
    if getattr(customer, "custom_rate_pct", None) is not None:
        rate = customer.custom_rate_pct
    else:
        rate = config["base_rate"]
        if customer.category == "ORO":
            rate = max(MIN_ALLOWED_RATE, rate - ORO_RATE_DISCOUNT)

    return {
        "active_debt":            active_debt,
        "available_amount":       UNLIMITED_AMOUNT,   # sin límite automático
        "interest_rate_monthly":  rate,
        "category":               customer.category,
        "score":                  customer.score,
        "risk_color":             customer.risk_color,
        "custom_rate":            getattr(customer, "custom_rate_pct", None) is not None,
    }


def get_applicable_rate(customer: "Customer | None") -> Decimal:
    """
    Tasa mensual sugerida para un nuevo contrato.

    El parámetro 'principal' fue eliminado: el monto no afecta la tasa.
    Jerarquía: custom_rate > categoría BD > BRONCE default.

    Nota: el cajero puede sobreescribir esta tasa en el momento de crear
    el contrato enviando 'interest_rate_monthly' en el payload.
    """
    if customer is not None and getattr(customer, "custom_rate_pct", None) is not None:
        return customer.custom_rate_pct

    if customer is not None:
        config = _get_category_config(customer.category)
        rate = config["base_rate"]
        if customer.category == "ORO":
            rate = max(MIN_ALLOWED_RATE, rate - ORO_RATE_DISCOUNT)
        return rate

    # Sin cliente: tasa default BRONCE
    return CATEGORY_CONFIG["BRONCE"]["base_rate"]
