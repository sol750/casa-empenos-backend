"""
Reporte de vitrina — contratos ELEGIBLE_VENTA / EN_VENTA.
GET /api/reports/vitrina
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PawnContract
from core.api.security import require_roles
from core.services.contract_state import get_contract_state, ContractState, calculate_recovery_amount


class VitrinaReportView(APIView):
    """
    Contratos candidatos a venta de garantía.
    Incluye EN_VENTA (dueño los puso en venta) y ELEGIBLE_VENTA (>90 días sin pago).

    ?branch=SUC-01   — filtrar por sucursal
    ?min_days=90     — mínimo de días de mora (default 30)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        today = timezone.now().date()
        min_days = int(request.query_params.get("min_days", 30))
        cutoff = today - timedelta(days=min_days)

        qs = (
            PawnContract.objects
            .select_related("branch", "customer")
            .prefetch_related("items", "payments", "amortizations")
            .filter(
                Q(status="ACTIVE", due_date__lt=cutoff) |
                Q(status="EN_VENTA")
            )
            .order_by("due_date")
        )

        if request.query_params.get("branch"):
            qs = qs.filter(branch__code=request.query_params["branch"].upper())

        results = []
        total_capital_risk = Decimal("0")

        for contract in qs:
            state = get_contract_state(contract, today)

            # Solo ELEGIBLE_VENTA y EN_VENTA
            if state not in (ContractState.ELEGIBLE_VENTA, ContractState.EN_VENTA,
                             ContractState.EN_MORA):
                continue

            recovery = calculate_recovery_amount(contract, today)
            days_overdue = (today - contract.due_date).days

            items = [
                {
                    "category":    i.category,
                    "description": i.description,
                    "condition":   i.condition,
                    "attributes":  i.attributes,
                }
                for i in contract.items.all()
            ]

            total_capital_risk += recovery["outstanding_principal"]

            results.append({
                "contract_number":    contract.contract_number,
                "pawn_contract_id":   str(contract.public_id),
                "state":              state,
                "branch_code":        contract.branch.code,
                "customer_full_name": contract.customer_full_name,
                "customer_ci":        contract.customer_ci,
                "principal_amount":   str(contract.principal_amount),
                "outstanding_principal": str(recovery["outstanding_principal"]),
                "interest_due":       str(recovery["interest_due"]),
                "total_to_recover":   str(recovery["total_to_recover"]),
                "due_date":           str(contract.due_date),
                "days_overdue":       days_overdue,
                "items":              items,
            })

        return Response({
            "as_of":                str(today),
            "count":                len(results),
            "total_capital_at_risk": str(total_capital_risk),
            "results":              results,
        })
