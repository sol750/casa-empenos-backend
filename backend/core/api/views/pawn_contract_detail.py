from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PawnContract
from core.models_security import UserRole
from core.services.interest_calc import prorated_interest


class PawnContractDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, contract_id):
        roles = set(UserRole.objects.filter(user=request.user).values_list("role__code", flat=True))
        allowed_roles = {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}
        if not roles.intersection(allowed_roles):
            return Response({"detail": "No tiene permisos."}, status=403)

        contract = PawnContract.objects.get(public_id=contract_id)

        # Acceso por sucursal
        if "OWNER_ADMIN" not in roles:
            if not request.user.branch_access.filter(branch_id=contract.branch_id).exists():
                return Response({"detail": "No tiene acceso a esta sucursal."}, status=403)

        totals = contract.payments.aggregate(
            principal_paid=Sum("principal_paid"),
            interest_paid=Sum("interest_paid"),
        )
        principal_paid_total = totals["principal_paid"] or Decimal("0.00")
        interest_paid_total = totals["interest_paid"] or Decimal("0.00")
        outstanding_principal = contract.principal_amount - principal_paid_total

        today = timezone.now().date()
        from_date = contract.interest_accrued_until or contract.start_date
        interest_accrued_now = prorated_interest(
            principal=outstanding_principal if outstanding_principal > 0 else Decimal("0.00"),
            monthly_rate_percent=contract.interest_rate_monthly,
            from_date=from_date,
            to_date=today,
        )

        payments = list(contract.payments.order_by("paid_at").values(
            "paid_at", "amount", "interest_paid", "principal_paid", "note"
        ))
        renewals = list(contract.renewals.order_by("renewed_at").values(
            "renewed_at", "previous_due_date", "new_due_date", "amount_charged", "interest_charged", "fee_charged", "note"
        ))

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
