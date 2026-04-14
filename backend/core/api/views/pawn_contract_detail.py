from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.models import PawnContract
from core.services.contract_state import get_contract_state, ContractState, calculate_recovery_amount
from core.api.security import require_roles, require_branch_access


class PawnContractDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, contract_id):
        allowed_roles = {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}

        # 1) Validar roles
        try:
            roles = require_roles(request.user, allowed_roles)
        except Exception as e:
            # PermissionDenied -> DRF lo convierte a 403, pero aquí mantenemos tu formato
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

        # 2) Traer contrato y validar existencia
        try:
            contract = (
                PawnContract.objects
                .select_related("branch", "customer")
                .prefetch_related("items", "payments", "renewals")
                .get(public_id=contract_id)
            )
        except PawnContract.DoesNotExist:
            return Response({"detail": "Contrato no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        # 3) Validar acceso por sucursal
        try:
            require_branch_access(request.user, contract.branch_id)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

        # 4) Totales y saldos
        totals = contract.payments.aggregate(
            principal_paid=Sum("principal_paid"),
            interest_paid=Sum("interest_paid"),
        )
        principal_paid_total = totals["principal_paid"] or Decimal("0.00")
        interest_paid_total = totals["interest_paid"] or Decimal("0.00")  # (por si luego lo usas)
        outstanding_principal = contract.principal_amount - principal_paid_total

        today = timezone.now().date()
        from_date = contract.interest_accrued_until or contract.start_date

        # Usar la máquina de estados para calcular el interés correctamente:
        # - Período de gracia (VENCIDO): interés congelado al due_date
        # - ACTIVO / EN_MORA: interés prorrateado hasta hoy
        recovery = calculate_recovery_amount(contract, today)
        interest_accrued_now = recovery["interest_due"]
        contract_state       = recovery["state"]

        # ── Pagos: nombres de campo ajustados a lo que espera el frontend ───
        payments = [
            {
                "payment_date":  p.paid_at,          # alias de paid_at
                "amount":        str(p.amount),
                "principal_paid": str(p.principal_paid),
                "interest_paid":  str(p.interest_paid),
                "note":          p.note,
            }
            for p in contract.payments.order_by("paid_at")
        ]

        # ── Renovaciones ──────────────────────────────────────────────────────
        renewals = [
            {
                "new_due_date":     str(r.new_due_date),
                "created_at":       r.renewed_at,    # alias de renewed_at
                "note":             r.note,
                "interest_charged": str(r.interest_charged),
                "fee_charged":      str(r.fee_charged),
                "amount_charged":   str(r.amount_charged),
            }
            for r in contract.renewals.order_by("renewed_at")
        ]

        # ── Artículos empeñados ───────────────────────────────────────────────
        items = [
            {
                "item_id":         str(item.public_id),
                "category":        item.category,
                "description":     item.description,
                "attributes":      item.attributes,
                "has_box":         item.has_box,
                "has_charger":     item.has_charger,
                "condition":       item.condition,
                "condition_notes": item.observations,
                "loan_amount":     str(item.loan_amount) if item.loan_amount is not None else None,
            }
            for item in contract.items.all()
        ]

        return Response(
            {
                "pawn_contract_id":      str(contract.public_id),
                "contract_number":       contract.contract_number,
                "status":                contract.status,
                "state":                 contract_state,
                "can_amortize":          recovery["can_amortize"],
                "can_recover":           recovery["can_recover"],
                "total_to_recover":      str(recovery["total_to_recover"]),
                "branch_code":           contract.branch.code,
                "customer_full_name":    contract.customer_full_name,
                "customer_ci":           contract.customer_ci,
                "principal_amount":      str(contract.principal_amount),
                "principal_paid_total":  str(principal_paid_total),
                "outstanding_principal": str(outstanding_principal),
                "interest_rate_monthly": str(contract.interest_rate_monthly),
                "interest_mode":         contract.interest_mode,
                "promo_note":            contract.promo_note,
                "start_date":            str(contract.start_date),
                "due_date":              str(contract.due_date),
                "interest_accrued_until": str(from_date),
                "interest_accrued_now":  str(interest_accrued_now),
                "items":    items,     # ← CRÍTICO: artículos empeñados
                "payments": payments,
                "renewals": renewals,
            }
        )
