from django.db import transaction

from core.models import BranchCounter


def next_pawn_contract_number(branch) -> str:
    """
    Genera PT1-000001 por sucursal (atómico).
    """
    with transaction.atomic():
        counter, _ = BranchCounter.objects.select_for_update().get_or_create(branch=branch)
        counter.pawn_contract_seq += 1
        counter.save(update_fields=["pawn_contract_seq"])

        return f"{branch.code}-{counter.pawn_contract_seq:06d}"
