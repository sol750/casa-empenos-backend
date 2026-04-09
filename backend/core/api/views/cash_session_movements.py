from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.models import CashSession, CashMovement
from core.api.serializers.cash_movement_list import CashMovementListSerializer
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes


class CashSessionMovementsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cash_session_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        try:
            session = CashSession.objects.select_related("branch", "cash_register").get(public_id=cash_session_id)
        except CashSession.DoesNotExist:
            return Response({"detail": "Sesión no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        # Acceso por sucursal
        if not is_owner_admin(request.user):
            allowed_codes = get_user_branch_codes(request.user)
            if session.branch and session.branch.code not in allowed_codes:
                return Response({"detail": "No tiene acceso a esta sucursal."}, status=status.HTTP_403_FORBIDDEN)

        qs = CashMovement.objects.select_related("branch", "cash_register", "cash_session", "performed_by") \
            .filter(cash_session=session) \
            .order_by("performed_at")

        return Response(CashMovementListSerializer(qs, many=True).data)
