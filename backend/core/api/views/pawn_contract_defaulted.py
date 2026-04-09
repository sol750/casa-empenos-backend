"""
Contratos en Mora (DEFAULTED)
==============================
GET /api/pawn-contracts/defaulted   → Lista paginada de contratos en mora

Filtros opcionales (query params):
    branch      → código de sucursal  (ej: ?branch=PT1)
    days_min    → días mínimos de mora (ej: ?days_min=30)
    days_max    → días máximos de mora
    ordering    → "days_overdue" | "-days_overdue" | "due_date" | "-due_date"
"""
from datetime import date

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models import PawnContract


class PawnContractDefaultedView(APIView):
    """
    GET /api/pawn-contracts/defaulted
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        qs = (
            PawnContract.objects
            .select_related("branch", "customer")
            .prefetch_related("items")
            .filter(status=PawnContract.Status.DEFAULTED)
        )

        # ── Filtros ───────────────────────────────────────────────────────────
        branch_code = request.query_params.get("branch")
        if branch_code:
            qs = qs.filter(branch__code=branch_code)

        days_min = request.query_params.get("days_min")
        days_max = request.query_params.get("days_max")

        today = date.today()
        contracts = list(qs)

        def days_overdue(c):
            return (today - c.due_date).days

        if days_min is not None:
            try:
                contracts = [c for c in contracts if days_overdue(c) >= int(days_min)]
            except ValueError:
                pass

        if days_max is not None:
            try:
                contracts = [c for c in contracts if days_overdue(c) <= int(days_max)]
            except ValueError:
                pass

        # ── Ordenamiento ──────────────────────────────────────────────────────
        ordering = request.query_params.get("ordering", "-days_overdue")
        reverse = ordering.startswith("-")
        key_name = ordering.lstrip("-")

        sort_keys = {
            "days_overdue": lambda c: days_overdue(c),
            "due_date":     lambda c: c.due_date,
        }
        sort_fn = sort_keys.get(key_name, sort_keys["days_overdue"])
        contracts.sort(key=sort_fn, reverse=reverse)

        # ── Serializar ────────────────────────────────────────────────────────
        data = []
        for c in contracts:
            overdue = days_overdue(c)
            items_preview = [
                {"category": it.category, "description": it.description}
                for it in c.items.all()[:3]
            ]
            data.append({
                "contract_number":  c.contract_number,
                "public_id":        str(c.public_id),
                "branch":           c.branch.code,
                "customer_name":    c.customer.full_name if c.customer else c.customer_full_name,
                "customer_ci":      c.customer.ci if c.customer else c.customer_ci,
                "customer_phone":   c.customer.phone if c.customer else None,
                "principal_amount": str(c.principal_amount),
                "due_date":         str(c.due_date),
                "defaulted_at":     c.defaulted_at.isoformat() if c.defaulted_at else None,
                "days_overdue":     overdue,
                "items_preview":    items_preview,
                "customer_score":   c.customer.score if c.customer else None,
                "customer_category": c.customer.category if c.customer else None,
            })

        # ── Resumen agregado ──────────────────────────────────────────────────
        total_exposure = sum(
            float(c.principal_amount) for c in contracts
        )

        return Response({
            "total":           len(data),
            "total_exposure":  f"{total_exposure:,.2f}",
            "contracts":       data,
        })
