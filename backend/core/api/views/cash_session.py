from django.db import transaction
from django.db.utils import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister, CashSession
from core.api.serializers.cash_session import CashSessionOpenSerializer
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes


class OpenCashSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CashSessionOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 🔐 Roles permitidos
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        # 1) Buscar caja
        try:
            cash_register = CashRegister.objects.select_related("branch").get(
                public_id=serializer.validated_data["cash_register_id"],
                is_active=True,
            )
        except CashRegister.DoesNotExist:
            return Response({"detail": "Caja no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        # 2) Caja GLOBAL solo OWNER_ADMIN
        if cash_register.register_type == CashRegister.RegisterType.GLOBAL:
            if not is_owner_admin(request.user):
                return Response(
                    {"detail": "Solo el dueño puede abrir caja global."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # 3) Validar acceso a sucursal si no es OWNER
        if cash_register.branch and not is_owner_admin(request.user):
            allowed_codes = get_user_branch_codes(request.user)
            if cash_register.branch.code not in allowed_codes:
                return Response({"detail": "No tiene acceso a esta sucursal."}, status=status.HTTP_403_FORBIDDEN)

        # 4) Crear sesión (con transacción y control de duplicado)
        try:
            with transaction.atomic():
                session = CashSession.objects.create(
                    cash_register=cash_register,
                    branch=cash_register.branch,
                    opened_by=request.user,
                    opening_amount=serializer.validated_data["opening_amount"],
                )
        except IntegrityError:
            # por constraint unique_open_cash_session_per_register
            return Response(
                {"detail": "Ya existe una sesión abierta para esta caja."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "cash_session_id": str(session.public_id),
                "cash_register_id": str(cash_register.public_id),
                "status": session.status,
                "opened_at": session.opened_at,
            },
            status=status.HTTP_201_CREATED,
        )
