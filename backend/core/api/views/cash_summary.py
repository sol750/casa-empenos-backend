from django.db.models import Sum, Count
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from core.models import CashSession, CashMovement, PawnContract, PawnPayment, PawnRenewal
from core.api.security import is_owner_admin, get_user_branch_codes


class CashSessionSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            session = CashSession.objects.select_related("branch").get(public_id=session_id)
        except CashSession.DoesNotExist:
            return Response({"detail": "Sesión no encontrada"}, status=404)

        # 🔐 Control de acceso
        if not is_owner_admin(request.user):
            allowed = get_user_branch_codes(request.user)
            if session.branch.code not in allowed:
                return Response({"detail": "Sin acceso a esta sucursal"}, status=403)

        # 🔹 Movimientos: _IN suman, _OUT restan (todos los montos son positivos)
        movements = CashMovement.objects.filter(cash_session=session)

        total_in = movements.filter(movement_type__endswith="_IN").aggregate(total=Sum("amount"))["total"] or 0
        total_out = movements.filter(movement_type__endswith="_OUT").aggregate(total=Sum("amount"))["total"] or 0

        # 🔹 Contratos creados
        contracts_count = PawnContract.objects.filter(disbursed_cash_session=session).count()

        # 🔹 Pagos
        payments = PawnPayment.objects.filter(cash_session=session)
        payments_count = payments.count()
        payments_total = payments.aggregate(total=Sum("amount"))["total"] or 0

        # 🔹 Renovaciones
        renewals = PawnRenewal.objects.filter(cash_session=session)
        renewals_count = renewals.count()
        renewals_total = renewals.aggregate(total=Sum("amount_charged"))["total"] or 0

        return Response({
            "session_id": str(session.public_id),
            "branch": session.branch.code,

            "cash_flow": {
                "total_in": str(total_in),
                "total_out": str(total_out),
                "net": str(total_in - total_out),
            },

            "operations": {
                "contracts_created": contracts_count,
                "payments_count": payments_count,
                "payments_total": str(payments_total),
                "renewals_count": renewals_count,
                "renewals_total": str(renewals_total),
            }
        })