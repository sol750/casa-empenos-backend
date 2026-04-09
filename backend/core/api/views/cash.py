from rest_framework.views import APIView
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core.models import CashSession


class CashSessionBalanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            session = CashSession.objects.select_related("cash_register", "branch").get(
                public_id=session_id
            )
        except CashSession.DoesNotExist:
            return Response({"detail": "Sesión no encontrada."}, status=404)

        return Response({
            "cash_session_id": str(session.public_id),
            "cash_register": session.cash_register.name,
            "branch": session.branch.name if session.branch else None,
            "expected_balance": str(session.expected_balance),
            "status": session.status,
        })