from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashRegister, CashSession
from core.models_security import UserRole
from core.api.serializers.cash_session import CashSessionOpenSerializer


class OpenCashSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CashSessionOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cash_register = CashRegister.objects.select_related("branch").get(
           public_id=serializer.validated_data["cash_register_id"], is_active=True,
        )

        # 🔐 Validar rol
        user_roles = set(
            UserRole.objects.filter(user=request.user).values_list("role__code", flat=True)
        )
        allowed_roles = {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}
        if not user_roles.intersection(allowed_roles):
            return Response(
                {"detail": "No tiene permisos para abrir caja."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 🔐 Caja global solo OWNER_ADMIN
        if cash_register.register_type == CashRegister.RegisterType.GLOBAL:
            if "OWNER_ADMIN" not in user_roles:
                return Response(
                    {"detail": "Solo el dueño puede abrir caja global."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # 🔐 Validar acceso a sucursal
        if cash_register.branch:
            has_access = request.user.branch_access.filter(
                branch=cash_register.branch
            ).exists()
            if not has_access:
                return Response(
                    {"detail": "No tiene acceso a esta sucursal."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # 🔒 Transacción
        with transaction.atomic():
            session = CashSession.objects.create(
                cash_register=cash_register,
                branch=cash_register.branch,
                opened_by=request.user,
                opening_amount=serializer.validated_data["opening_amount"],
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
