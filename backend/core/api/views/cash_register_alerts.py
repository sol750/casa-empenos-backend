from decimal import Decimal, InvalidOperation

from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister, CashSession
from core.models_security import UserRole


class CashRegisterAlertsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # min=300.00 (default)
        min_param = request.query_params.get("min", "300.00")
        try:
            min_amount = Decimal(min_param)
        except (InvalidOperation, TypeError):
            min_amount = Decimal("300.00")

        roles = set(UserRole.objects.filter(user=request.user).values_list("role__code", flat=True))

        qs = CashRegister.objects.select_related("branch").filter(is_active=True)

        # Si no es OWNER_ADMIN, solo cajas de sus sucursales (sin global)
        if "OWNER_ADMIN" not in roles:
            branch_ids = request.user.branch_access.values_list("branch_id", flat=True)
            qs = qs.filter(register_type=CashRegister.RegisterType.BRANCH, branch_id__in=branch_ids)

        alerts = []
        for cr in qs.order_by("register_type", "branch__code", "name"):
            session = CashSession.objects.filter(cash_register=cr, status=CashSession.Status.OPEN).first()
            if not session:
                continue  # solo alertamos sobre cajas operando (abiertas)

            mov_total = session.movements.aggregate(total=Sum("amount"))["total"] or 0
            expected = session.opening_amount + mov_total

            if expected < min_amount:
                alerts.append(
                    {
                        "cash_register_id": str(cr.public_id),
                        "name": cr.name,
                        "register_type": cr.register_type,
                        "branch_code": cr.branch.code if cr.branch else None,
                        "open_cash_session_id": str(session.public_id),
                        "expected_balance": str(expected),
                        "min_threshold": str(min_amount),
                        "shortfall": str(min_amount - expected),
                    }
                )

        return Response(alerts)