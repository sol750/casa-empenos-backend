"""
Módulo de Cola WhatsApp
=======================
POST /api/whatsapp/queue-reminders   → Encola recordatorios para contratos que vencen en N días
GET  /api/whatsapp/pending           → Lista mensajes pendientes (para el worker de envío)
POST /api/whatsapp/<public_id>/mark-sent  → Marcar como enviado (webhook del proveedor)
GET  /api/customers/<ci>/whatsapp    → Historial completo de un cliente

El envío real requiere integrar un proveedor de WhatsApp Business API
(Meta Cloud API, Twilio, etc.). Esta capa es el backend de la cola;
el worker de envío es un proceso separado (management command / Celery).
"""
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.models import Customer, PawnContract, WhatsAppMessage
from core.api.security import require_roles, is_owner_admin


def _build_reminder_body(contract: PawnContract) -> str:
    """
    Construye el cuerpo del mensaje de recordatorio de vencimiento.
    Formato compatible con plantillas de WhatsApp Business.
    """
    return (
        f"Hola {contract.customer.first_name}, te saludamos de "
        f"{contract.branch.name}. Tu contrato #{contract.contract_number} "
        f"vence el {contract.due_date.strftime('%d/%m/%Y')}. "
        f"Tu monto a pagar es ${contract.principal_amount:,}. "
        f"¡Ten un gran día!"
    )


def _build_overdue_body(contract: PawnContract, days_late: int) -> str:
    return (
        f"Hola {contract.customer.first_name}, te contactamos de "
        f"{contract.branch.name}. Tu contrato #{contract.contract_number} "
        f"tiene {days_late} día(s) de mora. "
        f"Por favor acércate a regularizar tu situación. ¡Gracias!"
    )


# ─────────────────────────────────────────────────────────────────────────────
class QueueDueRemindersView(APIView):
    """
    POST /api/whatsapp/queue-reminders
    Body: { "days_ahead": 3 }  (default: 3)

    Busca contratos ACTIVE cuyo due_date == hoy + days_ahead y
    encola un DUE_REMINDER para cada uno (evitando duplicados).
    Solo OWNER_ADMIN / SUPERVISOR.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        days_ahead = int(request.data.get("days_ahead", 3))
        if not 1 <= days_ahead <= 30:
            return Response({"detail": "days_ahead debe estar entre 1 y 30."}, status=400)

        target_date = timezone.localdate() + timezone.timedelta(days=days_ahead)

        contracts = (
            PawnContract.objects
            .filter(
                status=PawnContract.Status.ACTIVE,
                due_date=target_date,
                customer__isnull=False,   # solo contratos con cliente vinculado
            )
            .select_related("customer", "branch")
        )

        queued = 0
        skipped = 0  # ya tenía recordatorio pendiente para este contrato

        for contract in contracts:
            # Evitar duplicados: no crear si ya hay PENDING para este contrato+evento
            already_exists = WhatsAppMessage.objects.filter(
                contract=contract,
                event_type=WhatsAppMessage.EventType.DUE_REMINDER,
                status=WhatsAppMessage.Status.PENDING,
            ).exists()

            if already_exists:
                skipped += 1
                continue

            WhatsAppMessage.objects.create(
                customer      = contract.customer,
                contract      = contract,
                event_type    = WhatsAppMessage.EventType.DUE_REMINDER,
                phone_to      = contract.customer.phone,
                message_body  = _build_reminder_body(contract),
                scheduled_for = timezone.now(),  # enviar lo antes posible
            )
            queued += 1

        return Response({
            "target_date":        str(target_date),
            "contracts_found":    contracts.count(),
            "messages_queued":    queued,
            "messages_skipped":   skipped,
        })


# ─────────────────────────────────────────────────────────────────────────────
class QueueOverdueNoticesView(APIView):
    """
    POST /api/whatsapp/queue-overdue
    Encola avisos de mora para contratos vencidos (due_date < hoy).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        today = timezone.localdate()

        contracts = (
            PawnContract.objects
            .filter(
                status=PawnContract.Status.ACTIVE,
                due_date__lt=today,
                customer__isnull=False,
            )
            .select_related("customer", "branch")
        )

        queued = 0
        for contract in contracts:
            days_late = (today - contract.due_date).days

            already_exists = WhatsAppMessage.objects.filter(
                contract=contract,
                event_type=WhatsAppMessage.EventType.OVERDUE_NOTICE,
                status=WhatsAppMessage.Status.PENDING,
            ).exists()

            if already_exists:
                continue

            WhatsAppMessage.objects.create(
                customer      = contract.customer,
                contract      = contract,
                event_type    = WhatsAppMessage.EventType.OVERDUE_NOTICE,
                phone_to      = contract.customer.phone,
                message_body  = _build_overdue_body(contract, days_late),
                scheduled_for = timezone.now(),
            )
            queued += 1

        return Response({
            "overdue_contracts": contracts.count(),
            "messages_queued":   queued,
        })


# ─────────────────────────────────────────────────────────────────────────────
class WhatsAppPendingListView(APIView):
    """
    GET /api/whatsapp/pending
    Lista mensajes PENDING para que el worker externo los procese.
    Solo OWNER_ADMIN.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})

        messages = (
            WhatsAppMessage.objects
            .filter(
                status=WhatsAppMessage.Status.PENDING,
                scheduled_for__lte=timezone.now(),
            )
            .select_related("customer", "contract")
            .order_by("scheduled_for")[:100]
        )

        return Response({
            "count": messages.count(),
            "messages": [
                {
                    "public_id":    str(m.public_id),
                    "event_type":   m.event_type,
                    "phone_to":     m.phone_to,
                    "message_body": m.message_body,
                    "customer_ci":  m.customer.ci,
                    "contract_number": m.contract.contract_number if m.contract else None,
                    "scheduled_for": m.scheduled_for,
                }
                for m in messages
            ],
        })


# ─────────────────────────────────────────────────────────────────────────────
class WhatsAppMarkSentView(APIView):
    """
    POST /api/whatsapp/<public_id>/mark-sent
    Body: { "wa_message_id": "wamid.xxx", "new_status": "SENT|DELIVERED|READ|FAILED", "error_log": "" }
    Webhook del proveedor o confirmación manual.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, public_id):
        require_roles(request.user, {"OWNER_ADMIN"})

        try:
            msg = WhatsAppMessage.objects.get(public_id=public_id)
        except WhatsAppMessage.DoesNotExist:
            return Response({"detail": "Mensaje no encontrado."}, status=404)

        new_status = request.data.get("new_status", "SENT").upper()
        if new_status not in [s[0] for s in WhatsAppMessage.Status.choices]:
            return Response({"detail": "Estado inválido."}, status=400)

        msg.status        = new_status
        msg.wa_message_id = request.data.get("wa_message_id", "")
        msg.error_log     = request.data.get("error_log", "")

        if new_status == WhatsAppMessage.Status.SENT and not msg.sent_at:
            msg.sent_at = timezone.now()

        msg.save()

        return Response({"detail": "Estado actualizado.", "status": msg.status})


# ─────────────────────────────────────────────────────────────────────────────
class CustomerWhatsAppHistoryView(APIView):
    """
    GET /api/customers/<ci>/whatsapp
    Historial completo de mensajes de un cliente.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, ci):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        try:
            customer = Customer.objects.get(ci=ci.upper())
        except Customer.DoesNotExist:
            return Response({"detail": "Cliente no encontrado."}, status=404)

        messages = (
            WhatsAppMessage.objects
            .filter(customer=customer)
            .select_related("contract")
            .order_by("-created_at")
        )

        return Response({
            "customer_ci":   customer.ci,
            "customer_name": customer.full_name,
            "total":         messages.count(),
            "messages": [
                {
                    "public_id":    str(m.public_id),
                    "event_type":   m.event_type,
                    "status":       m.status,
                    "phone_to":     m.phone_to,
                    "message_body": m.message_body,
                    "scheduled_for": m.scheduled_for,
                    "sent_at":      m.sent_at,
                    "wa_message_id": m.wa_message_id,
                    "contract_number": m.contract.contract_number if m.contract else None,
                    "created_at":   m.created_at,
                }
                for m in messages
            ],
        })
