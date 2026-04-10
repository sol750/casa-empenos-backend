"""
Servicio de amortización de contratos.
Solo aplica cuando el contrato está en estado ACTIVO (today < due_date).
"""
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from core.services.contract_state import (
    get_contract_state,
    calculate_outstanding_principal,
    ContractState,
)
from core.services.interest_calc import prorated_interest


def calculate_amortization_preview(contract, capital_to_pay: Decimal, today: date = None) -> dict:
    """
    Calcula los montos de una amortización sin tocar la BD.
    Lanza ValueError si el contrato no está ACTIVO.
    """
    if today is None:
        today = date.today()

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
    interest_due = prorated_interest(
        principal=outstanding,
        monthly_rate_percent=contract.interest_rate_monthly,
        from_date=from_date,
        to_date=today,
    )

    new_principal = (outstanding - capital_to_pay).quantize(Decimal("0.01"))
    new_due_date  = today + relativedelta(months=1)
    total_to_pay  = (interest_due + capital_to_pay).quantize(Decimal("0.01"))

    return {
        "state":                  state,
        "outstanding_principal":  outstanding,
        "interest_due":           interest_due,
        "capital_to_pay":         capital_to_pay,
        "total_to_pay":           total_to_pay,
        "new_principal":          new_principal,
        "previous_due_date":      contract.due_date,
        "new_due_date":           new_due_date,
        "interest_rate_monthly":  contract.interest_rate_monthly,
    }


def create_amortization(contract, capital_to_pay: Decimal, cash_session, user, note: str = ""):
    """
    Ejecuta la amortización de forma atómica:
      1. Crea PawnPayment (contabilidad)
      2. Crea PawnAmortization (adenda)
      3. CashMovement PAYMENT_IN
      4. Actualiza due_date e interest_accrued_until del contrato
    Retorna (PawnAmortization, preview_dict).
    """
    from core.models import PawnContract, PawnPayment, PawnAmortization, CashMovement

    today = timezone.now().date()

    with transaction.atomic():
        contract = PawnContract.objects.select_for_update().get(pk=contract.pk)
        preview  = calculate_amortization_preview(contract, capital_to_pay, today)

        # 1) Pago contable (interés + capital)
        PawnPayment.objects.create(
            contract     = contract,
            cash_session = cash_session,
            paid_by      = user,
            amount       = preview["total_to_pay"],
            interest_paid = preview["interest_due"],
            principal_paid = capital_to_pay,
            note          = note or f"Amortización – adenda #{contract.amortizations.count() + 1}",
        )

        # 2) Registro de adenda
        amort = PawnAmortization.objects.create(
            contract           = contract,
            cash_session       = cash_session,
            performed_by       = user,
            outstanding_before = preview["outstanding_principal"],
            capital_paid       = capital_to_pay,
            interest_paid      = preview["interest_due"],
            previous_due_date  = contract.due_date,
            new_due_date       = preview["new_due_date"],
            note               = note,
        )

        # 3) Movimiento de caja
        CashMovement.objects.create(
            cash_session   = cash_session,
            cash_register  = cash_session.cash_register,
            branch         = cash_session.branch,
            movement_type  = CashMovement.MovementType.PAYMENT_IN,
            amount         = preview["total_to_pay"],
            performed_by   = user,
            note           = f"Amortización contrato {contract.contract_number}",
        )

        # 4) Actualizar contrato
        contract.due_date              = preview["new_due_date"]
        contract.interest_accrued_until = today
        contract.save(update_fields=["due_date", "interest_accrued_until"])

    return amort, preview
