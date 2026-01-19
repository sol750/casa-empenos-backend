from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.models import PawnContract
from core.services.interest_calc import prorated_interest
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
            contract = PawnContract.objects.select_related("branch").get(public_id=contract_id)
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
        interest_accrued_now = prorated_interest(
            principal=outstanding_principal if outstanding_principal > 0 else Decimal("0.00"),
            monthly_rate_percent=contract.interest_rate_monthly,
            from_date=from_date,
            to_date=today,
        )

        payments = list(
            contract.payments.order_by("paid_at").values(
                "paid_at", "amount", "interest_paid", "principal_paid", "note"
            )
        )
        renewals = list(
            contract.renewals.order_by("renewed_at").values(
                "renewed_at",
                "previous_due_date",
                "new_due_date",
                "amount_charged",
                "interest_charged",
                "fee_charged",
                "note",
            )
        )

        return Response(
            {
                "pawn_contract_id": str(contract.public_id),
                "contract_number": contract.contract_number,
                "status": contract.status,
                "branch_code": contract.branch.code,
                "customer_full_name": contract.customer_full_name,
                "customer_ci": contract.customer_ci,
                "principal_amount": str(contract.principal_amount),
                "principal_paid_total": str(principal_paid_total),
                "outstanding_principal": str(outstanding_principal),
                "interest_rate_monthly": str(contract.interest_rate_monthly),
                "start_date": str(contract.start_date),
                "due_date": str(contract.due_date),
                "interest_accrued_until": str(from_date),
                "interest_accrued_now": str(interest_accrued_now),
                "payments": payments,
                "renewals": renewals,
            }
        )
