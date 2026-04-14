"""
Motor de Valoración Inteligente (MVI).
Sugiere rangos de préstamo basados en historial, categoría y estado del artículo.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from core.models_mvi import MVIConfig

# ── Pureza por kilataje ───────────────────────────────────────────────────────
KARAT_PURITY = {
    8:  Decimal("0.333"),
    9:  Decimal("0.375"),
    10: Decimal("0.417"),
    12: Decimal("0.500"),
    14: Decimal("0.583"),
    18: Decimal("0.750"),
    20: Decimal("0.833"),
    22: Decimal("0.916"),
    24: Decimal("0.999"),
}

# ── Multiplicadores de condición ──────────────────────────────────────────────
CONDITION_FACTOR = {
    "EXCELLENT": Decimal("1.10"),
    "GOOD":      Decimal("1.00"),
    "WORN":      Decimal("0.75"),
    "DAMAGED":   Decimal("0.50"),
}

# ── Depreciación por categoría (fallback si no hay historial) ──────────────────
CATEGORY_DEPRECIATION_ATTR = {
    "PHONE":     "depreciation_phone_pct",
    "LAPTOP":    "depreciation_laptop_pct",
    "CONSOLE":   "depreciation_console_pct",
    "APPLIANCE": "depreciation_appliance_pct",
    "JEWELRY":   None,  # Joyería: valor intrínseco, no depreciación
    "INSTRUMENT": "depreciation_other_pct",
    "OTHER":     "depreciation_other_pct",
}


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Historial interno de préstamos similares
# ─────────────────────────────────────────────────────────────────────────────
def search_historical_loans(description: str, category: str) -> dict:
    """
    Busca contratos con artículos similares (keyword matching en description).
    Retorna estadísticas: promedio, último, rama, etc.
    """
    from django.db.models import Avg, Max, Min, Count, Q
    from core.models import PawnItem

    keywords = [w.strip() for w in description.lower().split() if len(w.strip()) >= 3][:6]

    base_q = Q(category=category)
    if keywords:
        kw_q = Q()
        for kw in keywords:
            kw_q |= Q(description__icontains=kw)
        base_q &= kw_q

    items = (
        PawnItem.objects
        .filter(base_q)
        .select_related("contract__branch")
        .filter(contract__status__in=["ACTIVE", "CLOSED"])
        .order_by("-contract__created_at")[:50]
    )

    if not items:
        return {"found": False, "count": 0}

    amounts = [item.contract.principal_amount for item in items]
    avg     = sum(amounts) / len(amounts)
    last    = items[0]

    return {
        "found":          True,
        "count":          len(amounts),
        "average":        _q(avg),
        "min":            _q(min(amounts)),
        "max":            _q(max(amounts)),
        "last_amount":    _q(last.contract.principal_amount),
        "last_branch":    last.contract.branch.code,
        "last_date":      str(last.contract.created_at.date()),
        "months_since_last": max(0, (date.today() - last.contract.created_at.date()).days // 30),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Precio de reventas similares (Compra Directa vendida)
# ─────────────────────────────────────────────────────────────────────────────
def search_sold_items(description: str, category: str) -> dict:
    """
    Busca artículos de Compra Directa ya vendidos con descripción similar.
    Aporta el 'Precio de Venta' real como referencia adicional.
    """
    from django.db.models import Q
    from core.models_inventory import DirectPurchase

    keywords = [w.strip() for w in description.lower().split() if len(w.strip()) >= 3][:6]
    base_q   = Q(category=category, status="VENDIDO")
    if keywords:
        kw_q = Q()
        for kw in keywords:
            kw_q |= Q(description__icontains=kw)
        base_q &= kw_q

    items = DirectPurchase.objects.filter(base_q).order_by("-sold_at")[:20]

    if not items:
        return {"found": False, "count": 0}

    sale_prices = [i.sale_price for i in items if i.sale_price]
    buy_prices  = [i.purchase_price for i in items]

    return {
        "found":              True,
        "count":              len(items),
        "avg_sale_price":     _q(sum(sale_prices) / len(sale_prices)) if sale_prices else None,
        "avg_purchase_price": _q(sum(buy_prices)  / len(buy_prices))  if buy_prices  else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Valor intrínseco de joyería
# ─────────────────────────────────────────────────────────────────────────────
def calculate_jewelry_value(karat: int, weight_grams: Decimal,
                             metal: str = "GOLD",
                             config=None) -> Optional[Decimal]:
    """
    Calcula el valor de fundición de una joya.
    metal: GOLD | SILVER
    """
    if config is None:
        config = MVIConfig.get()
    if metal == "SILVER":
        return _q(config.silver_price_gram_bs * weight_grams)

    purity = KARAT_PURITY.get(karat)
    if not purity:
        return None
    intrinsic = config.gold_price_24k_gram_bs * purity * weight_grams
    return _q(intrinsic)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Depreciación para tecnología
# ─────────────────────────────────────────────────────────────────────────────
def apply_depreciation(base_price: Decimal, category: str,
                        months_elapsed: int, config=None) -> Decimal:
    """Aplica depreciación compuesta: base × (1 - rate)^months."""
    if config is None:
        config = MVIConfig.get()
    attr   = CATEGORY_DEPRECIATION_ATTR.get(category, "depreciation_other_pct")
    if attr is None or months_elapsed <= 0:
        return base_price
    monthly_rate = getattr(config, attr) / Decimal("100")
    factor       = (Decimal("1") - monthly_rate) ** months_elapsed
    return _q(base_price * factor)


# ─────────────────────────────────────────────────────────────────────────────
# 5. FUNCIÓN PRINCIPAL: get_mvi_suggestion
# ─────────────────────────────────────────────────────────────────────────────
def get_mvi_suggestion(
    category: str,
    description: str,
    condition: str = "GOOD",
    attributes: dict = None,
    customer_category: str = None,   # ORO / PLATA / BRONCE / None
) -> dict:
    """
    Calcula la sugerencia de préstamo para un artículo.

    Retorna:
      references  → historial interno y ventas similares
      suggestion  → min / recommended / max / hard_max
      alerts      → advertencias contextuales
    """
    config     = MVIConfig.get()   # Fix #6: un solo DB hit, se pasa a las sub-funciones
    attributes = attributes or {}
    alerts     = []

    # ── A. Joyería: valor intrínseco ──────────────────────────────────────────
    intrinsic_value = None
    if category == "JEWELRY":
        karat_raw  = attributes.get("karat") or attributes.get("kilataje")
        weight_raw = attributes.get("weight_grams") or attributes.get("peso_gramos")
        metal      = (attributes.get("metal") or "GOLD").upper()
        if karat_raw and weight_raw:
            try:
                intrinsic_value = calculate_jewelry_value(
                    int(karat_raw), Decimal(str(weight_raw)), metal, config=config
                )
                alerts.append({
                    "type":    "INTRINSIC_VALUE_CALCULATED",
                    "message": f"Valor de fundición calculado: {intrinsic_value} Bs "
                               f"({karat_raw}k, {weight_raw}g, {metal})",
                })
            except Exception:
                alerts.append({"type": "INTRINSIC_VALUE_MISSING",
                                "message": "No se pudo calcular valor intrínseco. Verifica karat y peso."})

    # ── B. Historial interno ──────────────────────────────────────────────────
    history = search_historical_loans(description, category)
    sold    = search_sold_items(description, category)

    # ── C. Base de cálculo ────────────────────────────────────────────────────
    base_price = None
    depreciation_info = None

    if intrinsic_value:
        # Joyería: LTV sobre valor intrínseco
        base_price = _q(intrinsic_value * config.loan_to_value_pct / Decimal("100"))
    elif history["found"]:
        # Tecnología / otros: historial + depreciación
        months_elapsed = history.get("months_since_last", 0)
        dep_rate_attr  = CATEGORY_DEPRECIATION_ATTR.get(category, "depreciation_other_pct")
        dep_rate       = getattr(config, dep_rate_attr, Decimal("2.0")) if dep_rate_attr else Decimal("0")

        if months_elapsed > 0 and dep_rate > 0:
            raw_base   = history["last_amount"]
            base_price = apply_depreciation(raw_base, category, months_elapsed, config=config)
            depreciation_info = {
                "base_reference":    str(raw_base),
                "months_elapsed":    months_elapsed,
                "monthly_rate_pct":  str(dep_rate),
                "depreciated_value": str(base_price),
                "total_loss_pct":    str(_q((raw_base - base_price) / raw_base * 100)),
            }
            alerts.append({
                "type":    "DEPRECIATION_APPLIED",
                "message": f"Se aplicó {_q(dep_rate)}% mensual × {months_elapsed} meses = "
                           f"depreciación de {_q((raw_base - base_price) / raw_base * 100)}%",
            })
        else:
            base_price = history["average"]
    else:
        # Sin historial ni valor intrínseco: no hay sugerencia
        alerts.append({
            "type":    "NO_HISTORY",
            "message": f"Sin historial para '{description}' en categoría {category}. "
                       "El cajero debe tasar manualmente.",
        })

    # ── D. Ajuste por condición ───────────────────────────────────────────────
    condition_factor   = CONDITION_FACTOR.get(condition, Decimal("1.00"))
    condition_adjusted = _q(base_price * condition_factor) if base_price else None

    if condition != "GOOD" and base_price:
        alerts.append({
            "type":    "CONDITION_ADJUSTED",
            "message": f"Condición '{condition}': factor {condition_factor} aplicado.",
        })

    # ── E. Rangos ─────────────────────────────────────────────────────────────
    suggestion = None
    if condition_adjusted:
        recommended   = condition_adjusted
        min_rec       = _q(recommended * Decimal("0.90"))    # -10%
        max_rec       = _q(recommended * (Decimal("1") + config.soft_warning_pct / Decimal("100")))
        hard_max      = _q(recommended * (Decimal("1") + config.hard_block_pct  / Decimal("100")))

        # Bonus VIP (cliente ORO)
        vip_max = None
        if customer_category == "ORO":
            vip_max = _q(recommended * (Decimal("1") + config.vip_bonus_pct / Decimal("100")))
            alerts.append({
                "type":    "VIP_BONUS",
                "message": f"Cliente ORO: puede extender hasta {vip_max} Bs "
                           f"(+{config.vip_bonus_pct}% margen de confianza)",
            })

        suggestion = {
            "base_recommendation":  str(recommended),
            "condition_factor":     str(condition_factor),
            "min_recommended":      str(min_rec),
            "recommended":          str(recommended),
            "max_soft_warning":     str(max_rec),
            "hard_max_before_block": str(hard_max),
            "vip_max":              str(vip_max) if vip_max else None,
        }

    return {
        "category":    category,
        "description": description,
        "condition":   condition,
        "references": {
            "historical_loans": history,
            "sold_items":       sold,
            "intrinsic_value":  str(intrinsic_value) if intrinsic_value else None,
            "depreciation":     depreciation_info,
        },
        "suggestion": suggestion,
        "alerts":     alerts,
        "config_snapshot": {
            "gold_price_24k":    str(config.gold_price_24k_gram_bs),
            "loan_to_value_pct": str(config.loan_to_value_pct),
            "soft_warning_pct":  str(config.soft_warning_pct),
            "hard_block_pct":    str(config.hard_block_pct),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. Validar si un monto supera el límite MVI
# ─────────────────────────────────────────────────────────────────────────────
def validate_principal_against_mvi(
    principal: Decimal,
    suggestion: dict,
    contract_date=None,
) -> dict:
    """
    Retorna:
      status: OK | SOFT_WARNING | HARD_BLOCK | LEGACY_ADVISORY
      message: descripción

    Modo legado: si contract_date < 2026-01-01, el HARD_BLOCK se convierte en
    LEGACY_ADVISORY para permitir la migración de contratos históricos (2023-2025).
    """
    from datetime import date as _date

    LEGACY_CUTOFF = _date(2026, 1, 1)
    is_legacy = (
        contract_date is not None
        and isinstance(contract_date, _date)
        and contract_date < LEGACY_CUTOFF
    )

    if not suggestion or not suggestion.get("suggestion"):
        return {"status": "OK", "message": "Sin referencia MVI disponible."}

    s = suggestion["suggestion"]
    recommended = Decimal(s["recommended"])
    soft_max    = Decimal(s["max_soft_warning"])
    hard_max    = Decimal(s["hard_max_before_block"])

    if principal <= soft_max:
        return {"status": "OK", "message": "Monto dentro del rango recomendado."}

    if principal <= hard_max:
        return {
            "status":  "SOFT_WARNING",
            "message": f"El monto supera el recomendado ({recommended} Bs) en más de "
                       f"{suggestion['config_snapshot']['soft_warning_pct']}%. "
                       "Se registrará una advertencia.",
            "recommended":    str(recommended),
            "max_allowed_no_block": str(hard_max),
        }

    # HARD_BLOCK — pero si el contrato es legado (pre-2026), degradar a LEGACY_ADVISORY
    if is_legacy:
        return {
            "status":  "LEGACY_ADVISORY",
            "message": (
                f"Contrato legado ({contract_date}): el monto supera el límite MVI actual "
                f"({hard_max} Bs), pero se acepta sin bloqueo por ser anterior al 01/01/2026."
            ),
            "recommended": str(recommended),
            "hard_max":    str(hard_max),
            "legacy_mode": True,
        }

    return {
        "status":  "HARD_BLOCK",
        "message": f"El monto supera el límite máximo ({hard_max} Bs). "
                   "Requiere autorización del dueño antes de crear el contrato.",
        "recommended":   str(recommended),
        "hard_max":      str(hard_max),
        "requires_override": True,
    }
