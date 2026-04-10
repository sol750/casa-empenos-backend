"""
Reporte MVI — estadísticas de sobre-tasación y overrides.
GET /api/reports/mvi/overrides
GET /api/reports/mvi/stats
"""
from django.utils import timezone
from django.db.models import Count, Avg, Sum, Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models_mvi import AppraisalOverride
from core.api.security import require_roles


class MVIOverrideReportView(APIView):
    """
    GET /api/reports/mvi/overrides
    Lista todos los overrides con filtros.
    ?status=PENDING|APPROVED|DENIED
    ?branch=SUC-01
    ?from=YYYY-MM-DD  ?to=YYYY-MM-DD
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        qs = AppraisalOverride.objects.select_related(
            "branch", "requested_by", "authorized_by", "contract"
        ).order_by("-requested_at")

        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"].upper())
        if request.query_params.get("branch"):
            qs = qs.filter(branch__code=request.query_params["branch"].upper())
        if request.query_params.get("from"):
            qs = qs.filter(requested_at__date__gte=request.query_params["from"])
        if request.query_params.get("to"):
            qs = qs.filter(requested_at__date__lte=request.query_params["to"])

        results = []
        for ov in qs:
            excess_pct = None
            if ov.system_recommendation and ov.system_recommendation > 0:
                excess_pct = round(
                    float((ov.principal_requested - ov.system_recommendation)
                          / ov.system_recommendation * 100), 2
                )
            results.append({
                "override_id":           str(ov.public_id),
                "status":                ov.status,
                "branch_code":           ov.branch.code,
                "category":              ov.category,
                "description":           ov.description[:60],
                "condition":             ov.condition,
                "customer_ci":           ov.customer_ci,
                "system_recommendation": str(ov.system_recommendation),
                "principal_requested":   str(ov.principal_requested),
                "excess_pct":            excess_pct,
                "override_reason":       ov.override_reason,
                "requested_by":          ov.requested_by.get_full_name(),
                "requested_at":          str(ov.requested_at),
                "authorized_by":         ov.authorized_by.get_full_name() if ov.authorized_by else None,
                "authorized_at":         str(ov.authorized_at) if ov.authorized_at else None,
                "authorization_note":    ov.authorization_note,
                "contract_number":       ov.contract.contract_number if ov.contract else None,
            })

        return Response({"count": len(results), "results": results})


class MVIStatsReportView(APIView):
    """
    GET /api/reports/mvi/stats
    Estadísticas globales del MVI: cuántos contratos superaron el rango,
    por categoría, por sucursal, tasa de aprobación.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        total      = AppraisalOverride.objects.count()
        pending    = AppraisalOverride.objects.filter(status="PENDING").count()
        approved   = AppraisalOverride.objects.filter(status="APPROVED").count()
        denied     = AppraisalOverride.objects.filter(status="DENIED").count()

        by_category = (
            AppraisalOverride.objects
            .values("category")
            .annotate(count=Count("id"), approved=Count("id", filter=Q(status="APPROVED")))
            .order_by("-count")
        )

        by_branch = (
            AppraisalOverride.objects
            .values("branch__code")
            .annotate(count=Count("id"), approved=Count("id", filter=Q(status="APPROVED")))
            .order_by("-count")
        )

        by_cashier = (
            AppraisalOverride.objects
            .values("requested_by__first_name", "requested_by__last_name")
            .annotate(count=Count("id"), approved=Count("id", filter=Q(status="APPROVED")))
            .order_by("-count")[:10]
        )

        return Response({
            "summary": {
                "total":            total,
                "pending":          pending,
                "approved":         approved,
                "denied":           denied,
                "approval_rate_pct": round(approved / total * 100, 1) if total else 0,
            },
            "by_category": [
                {
                    "category": r["category"],
                    "total":    r["count"],
                    "approved": r["approved"],
                }
                for r in by_category
            ],
            "by_branch": [
                {
                    "branch_code": r["branch__code"],
                    "total":       r["count"],
                    "approved":    r["approved"],
                }
                for r in by_branch
            ],
            "top_requesters": [
                {
                    "cashier":  f"{r['requested_by__first_name']} {r['requested_by__last_name']}".strip(),
                    "total":    r["count"],
                    "approved": r["approved"],
                }
                for r in by_cashier
            ],
        })
