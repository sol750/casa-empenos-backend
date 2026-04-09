"""
Motor de Scoring de Clientes
============================
Se llama automáticamente cuando un contrato cambia a estado CLOSED.

Reglas de negocio:
  - Pago puntual (días_mora ≤ 0): +10 puntos
  - Pago tardío               : -5 puntos por cada día de mora (cap -30)

Recategorización automática:
  - Score ≥ 80  → ORO
  - Score ≥ 50  → PLATA
  - Score < 50  → BRONCE
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import PawnContract


def apply_contract_closure_score(contract: "PawnContract") -> dict:
    """
    Actualiza score y categoría del cliente al cerrar un contrato.

    Retorna un dict de auditoría con el resultado aplicado.
    Nunca lanza excepción: ante cualquier error retorna applied=False.
    """
    from core.models import Customer  # import local para evitar circular

    customer = getattr(contract, "customer", None)
    if customer is None:
        return {"applied": False, "reason": "sin_cliente_vinculado"}

    # ── Determinar si el pago fue puntual ──────────────────────────────────
    # Usamos el último pago registrado como referencia de fecha real
    last_payment = contract.payments.order_by("-paid_at").first()
    if last_payment is None:
        return {"applied": False, "reason": "sin_pagos_registrados"}

    payment_date = last_payment.paid_at.date()
    days_late = (payment_date - contract.due_date).days  # negativo = adelantado

    # ── Calcular delta de puntos ───────────────────────────────────────────
    if days_late <= 0:
        delta = +10
        customer.on_time_payments_count += 1
    else:
        # -5 por cada día de mora, mínimo -30 (cap en 6 días)
        delta = max(-30, -5 * days_late)
        customer.late_payments_count += 1

    # ── Aplicar y limitar score a [0, 100] ────────────────────────────────
    old_score    = customer.score
    old_category = customer.category

    customer.score = max(0, min(100, customer.score + delta))

    # ── Recategorizar ─────────────────────────────────────────────────────
    if customer.score >= 80:
        customer.category = Customer.Category.ORO
    elif customer.score >= 50:
        customer.category = Customer.Category.PLATA
    else:
        customer.category = Customer.Category.BRONCE

    customer.save(update_fields=[
        "score", "category",
        "late_payments_count", "on_time_payments_count",
        "updated_at",
    ])

    return {
        "applied":       True,
        "delta":         delta,
        "days_late":     days_late,
        "old_score":     old_score,
        "new_score":     customer.score,
        "old_category":  old_category,
        "new_category":  customer.category,
        "risk_color":    customer.risk_color,
    }


def increment_contract_count(customer) -> None:
    """
    Incrementa el contador de contratos al crear uno nuevo.
    Usa UPDATE atómico para evitar race conditions.
    """
    from django.db.models import F
    from core.models import Customer
    Customer.objects.filter(pk=customer.pk).update(
        total_contracts=F("total_contracts") + 1
    )
