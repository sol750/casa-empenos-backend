from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Branch
from core.models_security import Role, UserRole

OWNER_ROLE_CODE = "PROPIETARIO_ADMIN"


def _require_owner_admin(request):
    roles = set(UserRole.objects.filter(user=request.user).values_list("role__code", flat=True))
    return OWNER_ROLE_CODE in roles


class RolesMetaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _require_owner_admin(request):
            return Response({"detail": "Solo PROPIETARIO_ADMIN."}, status=403)

        data = list(Role.objects.all().values("code", "name"))
        return Response(data)


class BranchesMetaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _require_owner_admin(request):
            return Response({"detail": "Solo PROPIETARIO_ADMIN."}, status=403)

        data = list(Branch.objects.filter(is_active=True).values("code", "name"))
        return Response(data)
