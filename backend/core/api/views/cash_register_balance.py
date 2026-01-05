from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister, CashSession


class CashRegisterBalancesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_roles = set(request.user.user_roles.values_list("role__code", flat=True))

        qs = CashRegister.objects.select_related("branch").filter(is_active=True)

        # Si no es OWNER_ADMIN: solo sus sucursales y sin global
        if "OWNER_ADMIN" not in user_roles:
            branch_ids = request.user.branch_access.values_list("branch_id", flat=True)
            qs = qs.filter(register_type=CashRegister.RegisterType.BRANCH, branch_id__in=branch_ids)

        data = []
        for cr in qs.order_by("register_type", "branch__code", "name"):
            session = (
                CashSession.objects.filter(cash_register=cr, status=CashSession.Status.OPEN)
                .prefetch_related("movements")
                .first()
            )

            if session:
                mov_total = session.movements.aggregate(total=Sum("amount"))["total"] or 0
                expected = session.opening_amount + mov_total
                data.append(
                    {
                        "cash_register_id": str(cr.public_id),
                        "name": cr.name,
                        "register_type": cr.register_type,
                        "branch_code": cr.branch.code if cr.branch else None,
                        "open_cash_session_id": str(session.public_id),
                        "expected_balance": str(expected),
                    }
                )
            else:
                data.append(
                    {
                        "cash_register_id": str(cr.public_id),
                        "name": cr.name,
                        "register_type": cr.register_type,
                        "branch_code": cr.branch.code if cr.branch else None,
                        "open_cash_session_id": None,
                        "expected_balance": "0.00",
                    }
                )

        return Response(data)