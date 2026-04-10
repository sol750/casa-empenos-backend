"""
Notificación al dueño sobre overrides MVI pendientes.
GET  /api/mvi/overrides/pending-alert  — badge count + detalle para el panel del dueño
POST /api/mvi/overrides/whatsapp-alert — genera link wa.me para que el supervisor avise al dueño
"""
import urllib.parse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models_mvi import AppraisalOverride
from core.api.security import require_roles


class MVIOverridePendingAlertView(APIView):
    """
    GET /api/mvi/overrides/pending-alert
    Badge de alertas para el panel del dueño.
    Retorna el conteo y resumen de overrides pendientes.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        pending = AppraisalOverride.objects.select_related(
            "branch", "requested_by"
        ).filter(status="PENDING").order_by("-requested_at")

        items = []
        for ov in pending:
            items.append({
                "override_id":         str(ov.public_id),
                "branch_code":         ov.branch.code,
                "category":            ov.category,
                "description":         ov.description[:60],
                "principal_requested": str(ov.principal_requested),
                "system_recommendation": str(ov.system_recommendation),
                "requested_by":        ov.requested_by.get_full_name(),
                "requested_at":        str(ov.requested_at),
                "minutes_waiting":     int(
                    (timezone.now() - ov.requested_at).total_seconds() / 60
                ),
            })

        return Response({
            "pending_count": len(items),
            "has_pending":   len(items) > 0,
            "items":         items,
        })


class MVIOverrideWhatsAppAlertView(APIView):
    """
    POST /api/mvi/overrides/whatsapp-alert
    Genera un link wa.me con el texto del override para que el supervisor
    lo comparta con el dueño vía WhatsApp.

    Body: { "override_id": "<uuid>", "owner_phone": "+59171234567" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        override_id  = request.data.get("override_id")
        owner_phone  = request.data.get("owner_phone", "").strip()

        if not override_id:
            return Response({"detail": "'override_id' es requerido."}, status=400)

        try:
            ov = AppraisalOverride.objects.select_related("branch", "requested_by").get(
                public_id=override_id
            )
        except AppraisalOverride.DoesNotExist:
            return Response({"detail": "Override no encontrado."}, status=404)

        if ov.status != AppraisalOverride.Status.PENDING:
            return Response(
                {"detail": f"El override ya fue procesado ({ov.status})."},
                status=409,
            )

        msg = (
            f"⚠️ Autorización requerida — MVI\n"
            f"Sucursal: {ov.branch.code}\n"
            f"Cajero: {ov.requested_by.get_full_name()}\n"
            f"Artículo: {ov.description[:60]}\n"
            f"Condición: {ov.condition}\n"
            f"Sistema recomienda: {ov.system_recommendation} Bs\n"
            f"Cajero solicita: {ov.principal_requested} Bs\n"
            f"Motivo: {ov.override_reason}\n\n"
            f"Para AUTORIZAR: POST /api/mvi/overrides/{ov.public_id}/authorize\n"
            f"Para RECHAZAR:  POST /api/mvi/overrides/{ov.public_id}/deny"
        )

        encoded = urllib.parse.quote(msg)
        if owner_phone:
            phone_clean = owner_phone.replace("+", "").replace(" ", "")
            wa_link = f"https://wa.me/{phone_clean}?text={encoded}"
        else:
            wa_link = f"https://wa.me/?text={encoded}"

        return Response({
            "override_id":     str(ov.public_id),
            "whatsapp_link":   wa_link,
            "message_preview": msg,
        })
