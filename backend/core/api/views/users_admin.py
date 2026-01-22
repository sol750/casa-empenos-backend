from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.models_security import Role, UserRole, UserBranchAccess
from core.models import Branch
from core.api.serializers.user_admin import (
    UserListSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
)

User = get_user_model()

OWNER_ROLE_CODE = "OWNER_ADMIN"


def _require_owner_admin(request):
    roles = set(UserRole.objects.filter(user=request.user).values_list("role__code", flat=True))
    return OWNER_ROLE_CODE in roles


class UserListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _require_owner_admin(request):
            return Response({"detail": "Solo PROPIETARIO_ADMIN."}, status=403)

        qs = User.objects.all().order_by("id")
        return Response(UserListSerializer(qs, many=True).data)

    def post(self, request):
        if not _require_owner_admin(request):
            return Response({"detail": "Solo PROPIETARIO_ADMIN."}, status=403)

        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        is_active = serializer.validated_data.get("is_active", True)
        role_codes = serializer.validated_data["roles"]
        branch_codes = serializer.validated_data.get("branches", [])

        # Validaciones: roles existen
        roles = list(Role.objects.filter(code__in=role_codes))
        found = {r.code for r in roles}
        missing_roles = [c for c in role_codes if c not in found]
        if missing_roles:
            return Response(
                {"detail": "Roles inválidos.", "missing_roles": missing_roles},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validaciones: branches existen
        branches = list(Branch.objects.filter(code__in=branch_codes))
        found_b = {b.code for b in branches}
        missing_branches = [c for c in branch_codes if c not in found_b]
        if missing_branches:
            return Response(
                {"detail": "Sucursales inválidas.", "missing_branches": missing_branches},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(username=username).exists():
            return Response({"detail": "Username ya existe."}, status=400)

        with transaction.atomic():
            user = User.objects.create(username=username, is_active=is_active)
            user.set_password(password)
            user.save(update_fields=["password"])

            # Roles
            UserRole.objects.filter(user=user).delete()
            UserRole.objects.bulk_create([UserRole(user=user, role=r) for r in roles])

            # Branch access
            UserBranchAccess.objects.filter(user=user).delete()
            UserBranchAccess.objects.bulk_create([UserBranchAccess(user=user, branch=b) for b in branches])

        return Response(UserListSerializer(user).data, status=status.HTTP_201_CREATED)


class UserDetailUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id: int):
        if not _require_owner_admin(request):
            return Response({"detail": "Solo PROPIETARIO_ADMIN."}, status=403)

        user = User.objects.get(id=user_id)
        return Response(UserListSerializer(user).data)

    def patch(self, request, user_id: int):
        if not _require_owner_admin(request):
            return Response({"detail": "Solo PROPIETARIO_ADMIN."}, status=403)

        user = User.objects.get(id=user_id)

        serializer = UserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            if "is_active" in data:
                user.is_active = data["is_active"]
                user.save(update_fields=["is_active"])

            if "password" in data:
                user.set_password(data["password"])
                user.save(update_fields=["password"])

            if "roles" in data:
                role_codes = data["roles"]
                roles = list(Role.objects.filter(code__in=role_codes))
                found = {r.code for r in roles}
                missing_roles = [c for c in role_codes if c not in found]
                if missing_roles:
                    return Response(
                        {"detail": "Roles inválidos.", "missing_roles": missing_roles},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                UserRole.objects.filter(user=user).delete()
                UserRole.objects.bulk_create([UserRole(user=user, role=r) for r in roles])

            if "branches" in data:
                branch_codes = data["branches"]
                branches = list(Branch.objects.filter(code__in=branch_codes))
                found_b = {b.code for b in branches}
                missing_branches = [c for c in branch_codes if c not in found_b]
                if missing_branches:
                    return Response(
                        {"detail": "Sucursales inválidas.", "missing_branches": missing_branches},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                UserBranchAccess.objects.filter(user=user).delete()
                UserBranchAccess.objects.bulk_create([UserBranchAccess(user=user, branch=b) for b in branches])

        return Response(UserListSerializer(user).data, status=200)
