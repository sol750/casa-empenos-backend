from django.db import transaction
from django.db.utils import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister, CashSession
from core.api.serializers.cash_session import CashSessionOpenSerializer
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes
from core.services.cash_alerts import validate_opening_vs_previous


class OpenCashSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CashSessionOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        # 1) Buscar caja
        try:
            cash_register = CashRegister.objects.select_related("branch").get(
                public_id=serializer.validated_data["cash_register_id"],
                is_active=True,
            )
        except CashRegister.DoesNotExist:
            return Response({"detail": "Caja no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        # 2) Bóveda y Global solo OWNER_ADMIN
        if cash_register.register_type in (
            CashRegister.RegisterType.GLOBAL,
            CashRegister.RegisterType.VAULT,
        ):
            if not is_owner_admin(request.user):
                return Response(
                    {"detail": "Solo el dueño puede abrir bóveda o caja global."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # 3) Validar acceso a sucursal si no es OWNER
        if cash_register.branch and not is_owner_admin(request.user):
            allowed_codes = get_user_branch_codes(request.user)
            if cash_register.branch.code not in allowed_codes:
                return Response({"detail": "No tiene acceso a esta sucursal."}, status=status.HTTP_403_FORBIDDEN)

        opening_amount = serializer.validated_data["opening_amount"]

        # 4) Validar mínimo operativo
        alerts = []
        if opening_amount < cash_register.min_balance:
            alerts.append({
                "level":  "CRITICAL",
                "code":   "BELOW_MINIMUM",
                "message": (
                    f"La caja abre con Bs.{opening_amount:,.2f}, por debajo del "
                    f"mínimo operativo de Bs.{cash_register.min_balance:,.2f}. "
                    f"Se recomienda fondear antes de operar."
                ),
            })

        # 5) Comparar con cierre del día anterior
        opening_check = validate_opening_vs_previous(opening_amount, cash_register)
        if opening_check["alert"]:
            alerts.append(opening_check["alert"])

        # 6) Crear sesión
        try:
            with transaction.atomic():
                session = CashSession.objects.create(
                    cash_register  = cash_register,
                    branch         = cash_register.branch,
                    opened_by      = request.user,
                    opening_amount = opening_amount,
                )
        except IntegrityError:
            return Response(
                {"detail": "Ya existe una sesión abierta para esta caja."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "cash_session_id":  str(session.public_id),
                "cash_register_id": str(cash_register.public_id),
                "register_type":    cash_register.register_type,
                "status":           session.status,
                "opened_at":        session.opened_at,
                "opening_amount":   str(opening_amount),
                "previous_closing": opening_check["previous"],
                "opening_diff":     opening_check["diff"],
                "min_balance":      str(cash_register.min_balance),
                "max_balance":      str(cash_register.max_balance),
                "alerts":           alerts,
            },
            status=status.HTTP_201_CREATED,
        )
