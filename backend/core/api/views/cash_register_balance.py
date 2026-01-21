from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister, CashSession
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes


class CashRegisterBalancesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Roles permitidos para ver balances
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        qs = CashRegister.objects.select_related("branch").filter(is_active=True)

        # Si no es OWNER_ADMIN: solo sus sucursales y sin global
        if not is_owner_admin(request.user):
            branch_codes = get_user_branch_codes(request.user)
            qs = qs.filter(
                register_type=CashRegister.RegisterType.BRANCH,
                branch__code__in=branch_codes,
            )

        data = []
        for cr in qs.order_by("register_type", "branch__code", "name"):
            session = (
                CashSession.objects.select_related("cash_register", "branch")
                .filter(cash_register=cr, status=CashSession.Status.OPEN)
                .first()
            )

            if session:
                expected = session.expected_balance
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
