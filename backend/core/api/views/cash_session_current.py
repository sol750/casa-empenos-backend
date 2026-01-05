from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashSession, CashRegister
from core.models_security import UserRole
from core.api.serializers.cash_session_current import CashSessionCurrentSerializer


class CurrentCashSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_roles = set(
            UserRole.objects.filter(user=request.user).values_list("role__code", flat=True)
        )

        allowed_roles = {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}
        if not user_roles.intersection(allowed_roles):
            return Response([], status=200)

        qs = CashSession.objects.select_related(
            "cash_register", "branch"
        ).filter(status=CashSession.Status.OPEN)

        # OWNER_ADMIN puede ver todas las abiertas
        if "OWNER_ADMIN" in user_roles:
            data = CashSessionCurrentSerializer(qs, many=True).data
            return Response(data)

        # CAJERO/SUPERVISOR → solo sesiones de sus sucursales
        branch_ids = request.user.branch_access.values_list("branch_id", flat=True)
        qs = qs.filter(branch_id__in=branch_ids)

        data = CashSessionCurrentSerializer(qs, many=True).data
        return Response(data)