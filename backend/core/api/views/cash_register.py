from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister
from core.models_security import UserRole
from core.api.serializers.cash_register import CashRegisterListSerializer


class CashRegisterListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_roles = set(
            UserRole.objects.filter(user=request.user).values_list("role__code", flat=True)
        )

        # Base query
        qs = CashRegister.objects.select_related("branch").filter(is_active=True)

        # OWNER_ADMIN ve todo
        if "OWNER_ADMIN" in user_roles:
            data = CashRegisterListSerializer(qs.order_by("register_type", "branch__code", "name"), many=True).data
            return Response(data)

        # CAJERO/SUPERVISOR: solo cajas de sus sucursales, NO global
        allowed_roles = {"CAJERO", "SUPERVISOR"}
        if user_roles.intersection(allowed_roles):
            branch_ids = request.user.branch_access.values_list("branch_id", flat=True)
            qs = qs.filter(register_type=CashRegister.RegisterType.BRANCH, branch_id__in=branch_ids)
            data = CashRegisterListSerializer(qs.order_by("branch__code", "name"), many=True).data
            return Response(data)

        # AUDITOR u otros: por ahora lectura restringida (puedes decidir)
        return Response([], status=200)
