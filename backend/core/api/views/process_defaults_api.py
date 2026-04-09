"""
API: Procesar mora manualmente
===============================
POST /api/pawn-contracts/process-defaults
    → Ejecuta el procesador de mora (equivale al cron diario)
    → Solo SUPERVISOR / OWNER_ADMIN

Query params:
    dry_run=true  → no persiste cambios (útil para previsualizar)
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.api.security import require_roles
from core.services.default_processor import mark_defaulted_contracts


class ProcessDefaultsView(APIView):
    """
    POST /api/pawn-contracts/process-defaults
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        dry_run = request.query_params.get("dry_run", "false").lower() == "true"

        result = mark_defaulted_contracts(dry_run=dry_run)

        return Response(result, status=status.HTTP_200_OK)
