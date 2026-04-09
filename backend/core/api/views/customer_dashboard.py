"""
Dashboard ejecutivo del cliente
GET /api/customers/<ci>/dashboard

Devuelve el resumen completo que el cajero necesita antes de crear
un nuevo contrato o registrar un pago:

  ┌──────────────────────────────────────────────────────────────┐
  │  STATUS DE RIESGO    │  Verde / Amarillo / Rojo + score      │
  │  RESUMEN DE DEUDA    │  Contratos abiertos + capital total    │
  │  LÍNEA DE CRÉDITO    │  Cuánto puede pedir hoy y a qué tasa  │
  │  HISTORIAL WHATSAPP  │  Últimos 10 mensajes enviados          │
  │  HISTORIAL CONTRATOS │  Últimos 5 contratos (resumen)         │
  └──────────────────────────────────────────────────────────────┘
"""
from decimal import Decimal

from django.db.models import Sum, Count, Q
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Customer, PawnContract, WhatsAppMessage
from core.api.security import require_roles
from core.services.credit_line_calc import calculate_credit_line


class CustomerDashboardView(APIView):
    """
    Resumen ejecutivo de un cliente identificado por su CI.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, ci):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        # ── Cargar cliente ────────────────────────────────────────────────────
        try:
            customer = Customer.objects.prefetch_related("references").get(ci=ci.upper())
        except Customer.DoesNotExist:
            return Response({"detail": "Cliente no encontrado."}, status=404)

        # ── Bloque 1: Identidad y riesgo ──────────────────────────────────────
        identity = {
            "public_id":          str(customer.public_id),
            "ci":                 customer.ci,
            "full_name":          customer.full_name,
            "phone":              customer.phone,
            "category":           customer.category,
            "score":              customer.score,
            "risk_color":         customer.risk_color,
            "is_blacklisted":     customer.is_blacklisted,
            "blacklist_reason":   customer.blacklist_reason,
        }

        # ── Bloque 2: Resumen de deuda activa ─────────────────────────────────
        active_contracts_qs = PawnContract.objects.filter(
            customer=customer, status=PawnContract.Status.ACTIVE
        ).select_related("branch")

        active_stats = active_contracts_qs.aggregate(
            total_principal=Sum("principal_amount"),
            count=Count("id"),
        )

        today = timezone.localdate()
        overdue_count = active_contracts_qs.filter(due_date__lt=today).count()

        active_list = [
            {
                "contract_number":   c.contract_number,
                "branch":            c.branch.code,
                "principal_amount":  str(c.principal_amount),
                "interest_rate":     str(c.interest_rate_monthly),
                "due_date":          str(c.due_date),
                "days_to_due":       (c.due_date - today).days,
                "is_overdue":        c.due_date < today,
            }
            for c in active_contracts_qs.order_by("due_date")
        ]

        debt_summary = {
            "active_contracts_count":  active_stats["count"] or 0,
            "total_principal_active":  str(active_stats["total_principal"] or Decimal("0.00")),
            "overdue_contracts_count": overdue_count,
            "contracts":               active_list,
        }

        # ── Bloque 3: Línea de crédito VIP ────────────────────────────────────
        credit_line = calculate_credit_line(customer)
        credit_line_block = {
            "max_amount":            str(credit_line["max_amount"]),
            "active_debt":           str(credit_line["active_debt"]),
            "available_amount":      str(credit_line["available_amount"]),
            "interest_rate_monthly": str(credit_line["interest_rate_monthly"]),
            "category":              credit_line["category"],
            "score":                 credit_line["score"],
            "message": (
                f"Este cliente puede empeñar hoy hasta "
                f"${credit_line['available_amount']:,} "
                f"con tasa del {credit_line['interest_rate_monthly']}% mensual."
            ),
        }

        # ── Bloque 4: Historial WhatsApp (últimos 10) ─────────────────────────
        wa_messages = (
            WhatsAppMessage.objects
            .filter(customer=customer)
            .order_by("-created_at")[:10]
        )
        wa_history = [
            {
                "public_id":    str(m.public_id),
                "event_type":   m.event_type,
                "status":       m.status,
                "scheduled_for": m.scheduled_for,
                "sent_at":      m.sent_at,
                "contract_number": (
                    m.contract.contract_number if m.contract else None
                ),
            }
            for m in wa_messages
        ]

        # ── Bloque 5: Historial de contratos (últimos 5) ──────────────────────
        past_contracts = (
            PawnContract.objects
            .filter(customer=customer)
            .order_by("-created_at")[:5]
        )
        contract_history = [
            {
                "contract_number": c.contract_number,
                "status":          c.status,
                "principal_amount": str(c.principal_amount),
                "start_date":      str(c.start_date),
                "due_date":        str(c.due_date),
                "branch":          c.branch.code,
            }
            for c in past_contracts
        ]

        # ── Estadísticas de fidelidad ─────────────────────────────────────────
        loyalty = {
            "total_contracts":        customer.total_contracts,
            "on_time_payments_count": customer.on_time_payments_count,
            "late_payments_count":    customer.late_payments_count,
            "punctuality_rate": (
                round(
                    customer.on_time_payments_count
                    / max(1, customer.on_time_payments_count + customer.late_payments_count)
                    * 100,
                    1,
                )
            ),
        }

        return Response({
            "identity":        identity,
            "debt_summary":    debt_summary,
            "credit_line":     credit_line_block,
            "loyalty":         loyalty,
            "whatsapp_history": wa_history,
            "contract_history": contract_history,
        })
