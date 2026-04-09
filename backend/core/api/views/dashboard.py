from decimal import Decimal
from django.db.models import Sum
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core.models import CashSession


class CashDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        sessions = CashSession.objects.select_related(
            "cash_register", "branch"
        ).filter(status=CashSession.Status.OPEN)

        total_company = Decimal("0.00")
        branches = {}

        for session in sessions:
            balance = session.expected_balance

            total_company += balance

            branch_name = session.branch.name if session.branch else "Sin sucursal"

            if branch_name not in branches:
                branches[branch_name] = {
                    "total": Decimal("0.00"),
                    "cash_registers": []
                }

            branches[branch_name]["total"] += balance

            branches[branch_name]["cash_registers"].append({
                "cash_session_id": str(session.public_id),
                "cash_register": session.cash_register.name,
                "balance": str(balance)
            })

        return Response({
            "total_company_balance": str(total_company),
            "branches": branches
        })