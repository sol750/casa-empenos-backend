from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models_security import UserRole, UserBranchAccess
from core.api.serializers.me import MeSerializer


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        roles = list(
            UserRole.objects.filter(user=request.user)
            .values_list("role__code", flat=True)
        )

        branches = list(
            UserBranchAccess.objects.filter(user=request.user)
            .values_list("branch__code", flat=True)
        )

        payload = {
            "user_id": request.user.id,
            "username": request.user.username,
            "roles": roles,
            "branches": branches,
        }
        return Response(MeSerializer(payload).data)
