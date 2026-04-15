"""
Servicio de amortización de contratos.
Solo aplica cuando el contrato está en estado ACTIVO (today < due_date).

Regla de negocio:
  - La fecha de vencimiento NO se modifica al amortizar. El cliente sigue
    teniendo la misma fecha de renovación/cierre que al crear el contrato.
  - Al cerrar un contrato con amortizaciones previas, el interés a cobrar
    es el interés original del primer mes (principal_amount × tasa mensual),
    no un prorrateo por días. Esto se aplica en pawn_payment.py.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.services.contract_state import (
    get_contract_state,
    calculate_outstanding_principal,
    ContractState,
)
from core.services.interest_calc import fixed_interest_for_period


def calculate_amortization_preview(
    contract,
    capital_to_pay: Decimal,
    today: date = None,
    effective_date: date = None,
) -> dict:
    """
    Calcula los montos de una amortización sin tocar la BD.
    Lanza ValueError si el contrato no está ACTIVO.
    La fecha de vencimiento no cambia.

    effective_date — Fase de Sincronización: fecha real del pago según libros físicos.
    Si se provee, el interés se calcula por los meses transcurridos desde
    interest_accrued_until hasta effective_date.
    """
    if today is None:
        today = timezone.now().date()
    if effective_date is None:
        effective_date = today

    state = get_contract_state(contract, today)
    if state != ContractState.ACTIVO:
        raise ValueError(
            f"Solo se puede amortizar contratos ACTIVOS. Estado actual: {state}"
        )

    outstanding = calculate_outstanding_principal(contract)

    if capital_to_pay <= Decimal("0"):
        raise ValueError("El monto de capital a amortizar debe ser mayor a 0.")

    if capital_to_pay >= outstanding:
        raise ValueError(
            f"El monto de capital ({capital_to_pay}) debe ser menor al saldo pendiente "
            f"({outstanding}). Para cancelar la deuda completa use el endpoint de pago."
        )

    from_date = contract.interest_accrued_until or contract.start_date
    interest_due = fixed_interest_for_period(
        outstanding,
        contract.interest_rate_monthly,
        from_date=from_date,
        to_date=effective_date,
    )

    new_principal = (outstanding - capital_to_pay).quantize(Decimal("0.01"))
    total_to_pay  = (interest_due + capital_to_pay).quantize(Decimal("0.01"))

    # La fecha de vencimiento permanece igual — no se renueva al amortizar
    return {
        "state":                  state,
        "outstanding_principal":  outstanding,
        "interest_due":           interest_due,
        "capital_to_pay":         capital_to_pay,
        "total_to_pay":           total_to_pay,
        "new_principal":          new_principal,
        "previous_due_date":      contract.due_date,
        "new_due_date":           contract.due_date,   # sin cambio
        "interest_rate_monthly":  contract.interest_rate_monthly,
        "effective_date":         effective_date,
    }


def create_amortization(
    contract,
    capital_to_pay: Decimal,
    cash_session,
    user,
    note: str = "",
    effective_date: date = None,
):
    """
    Ejecuta la amortización de forma atómica:
      1. Crea PawnPayment (contabilidad)
      2. Crea PawnAmortization (adenda)
      3. CashMovement PAYMENT_IN
      4. Actualiza interest_accrued_until (la due_date NO cambia)
    Retorna (PawnAmortization, preview_dict).

    effective_date — Fase de Sincronización: si se provee, el interés cubre
    desde interest_accrued_until hasta esa fecha y CashMovement.effective_date
    se marca retroactivamente.
    """
    from core.models import PawnContract, PawnPayment, PawnAmortization, CashMovement

    today = timezone.now().date()
    if effective_date is None:
        effective_date = today

    with transaction.atomic():
        contract = PawnContract.objects.select_for_update().get(pk=contract.pk)
        preview  = calculate_amortization_preview(contract, capital_to_pay, today, effective_date)

        # 1) Pago contable (interés + capital)
        PawnPayment.objects.create(
            contract       = contract,
            cash_session   = cash_session,
            paid_by        = user,
            amount         = preview["total_to_pay"],
            interest_paid  = preview["interest_due"],
            principal_paid = capital_to_pay,
            note           = note or f"Amortización – adenda #{contract.amortizations.count() + 1}",
        )

        # 2) Registro de adenda (new_due_date == previous_due_date: sin cambio)
        amort = PawnAmortization.objects.create(
            contract           = contract,
            cash_session       = cash_session,
            performed_by       = user,
            outstanding_before = preview["outstanding_principal"],
            capital_paid       = capital_to_pay,
            interest_paid      = preview["interest_due"],
            previous_due_date  = contract.due_date,
            new_due_date       = contract.due_date,   # sin cambio
            note               = note,
        )

        # 3) Movimiento de caja (retroactivo si effective_date != hoy)
        CashMovement.objects.create(
            cash_session   = cash_session,
            cash_register  = cash_session.cash_register,
            branch         = cash_session.branch,
            movement_type  = CashMovement.MovementType.PAYMENT_IN,
            amount         = preview["total_to_pay"],
            performed_by   = user,
            note           = f"Amortización contrato {contract.contract_number}",
            effective_date = effective_date if effective_date != today else None,
        )

        # 4) Actualizar solo interest_accrued_until — due_date no cambia
        contract.interest_accrued_until = effective_date
        contract.save(update_fields=["interest_accrued_until"])

    return amort, preview
