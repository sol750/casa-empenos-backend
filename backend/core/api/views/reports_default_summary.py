"""
Reporte de Mora / Default Summary
===================================
GET /api/reports/default-summary

Retorna:
  - Resumen global de cartera en mora
  - Desglose por sucursal
  - Distribución por tramos de días de mora
  - Top 10 contratos por exposición
  - Evolución histórica (últimos 30 días de defaults registrados)
"""
from datetime import date, timedelta
from decimal import Decimal

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models import Branch, PawnContract


class DefaultSummaryReportView(APIView):
    """
    GET /api/reports/default-summary
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        today = date.today()

        defaulted_qs = (
            PawnContract.objects
            .select_related("branch", "customer")
            .filter(status=PawnContract.Status.DEFAULTED)
        )

        active_qs = PawnContract.objects.filter(status=PawnContract.Status.ACTIVE)

        # ── Métricas globales ─────────────────────────────────────────────────
        defaulted_list = list(defaulted_qs)
        total_defaulted = len(defaulted_list)
        total_active    = active_qs.count()
        total_portfolio = total_defaulted + total_active

        def exposure(c):
            return float(c.principal_amount)

        total_exposure_defaulted = sum(exposure(c) for c in defaulted_list)
        default_rate_pct = (
            round(total_defaulted / total_portfolio * 100, 2)
            if total_portfolio > 0 else 0.0
        )

        def days_overdue(c):
            return max(0, (today - c.due_date).days)

        avg_days = (
            round(sum(days_overdue(c) for c in defaulted_list) / total_defaulted, 1)
            if total_defaulted > 0 else 0
        )

        # ── Desglose por sucursal ─────────────────────────────────────────────
        branch_map = {}
        for c in defaulted_list:
            code = c.branch.code
            if code not in branch_map:
                branch_map[code] = {"branch": code, "count": 0, "exposure": Decimal("0")}
            branch_map[code]["count"] += 1
            branch_map[code]["exposure"] += c.principal_amount

        by_branch = [
            {
                "branch":   v["branch"],
                "count":    v["count"],
                "exposure": f"{v['exposure']:,.2f}",
            }
            for v in sorted(branch_map.values(), key=lambda x: -x["count"])
        ]

        # ── Distribución por tramos de mora ───────────────────────────────────
        tramos = [
            ("1-30",   1,   30),
            ("31-60",  31,  60),
            ("61-90",  61,  90),
            ("91-180", 91,  180),
            ("181+",   181, 99999),
        ]
        by_tramo = []
        for label, lo, hi in tramos:
            group = [c for c in defaulted_list if lo <= days_overdue(c) <= hi]
            by_tramo.append({
                "tramo":    label,
                "count":    len(group),
                "exposure": f"{sum(float(c.principal_amount) for c in group):,.2f}",
            })

        # ── Top 10 por exposición ─────────────────────────────────────────────
        top10 = sorted(defaulted_list, key=exposure, reverse=True)[:10]
        top_contracts = [
            {
                "contract_number":  c.contract_number,
                "branch":           c.branch.code,
                "customer_name":    c.customer.full_name if c.customer else c.customer_full_name,
                "customer_ci":      c.customer.ci if c.customer else c.customer_ci,
                "principal_amount": str(c.principal_amount),
                "due_date":         str(c.due_date),
                "days_overdue":     days_overdue(c),
            }
            for c in top10
        ]

        # ── Evolución últimos 30 días (defaults nuevos por día) ───────────────
        thirty_days_ago = today - timedelta(days=30)
        recent = [
            c for c in defaulted_list
            if c.defaulted_at and c.defaulted_at.date() >= thirty_days_ago
        ]
        day_counter = {}
        for c in recent:
            d = str(c.defaulted_at.date())
            day_counter[d] = day_counter.get(d, 0) + 1

        evolution = [
            {"date": d, "new_defaults": n}
            for d, n in sorted(day_counter.items())
        ]

        return Response({
            "generated_at": today.isoformat(),
            "summary": {
                "total_defaulted":         total_defaulted,
                "total_active":            total_active,
                "total_portfolio":         total_portfolio,
                "default_rate_pct":        default_rate_pct,
                "total_exposure_defaulted": f"{total_exposure_defaulted:,.2f}",
                "avg_days_overdue":         avg_days,
            },
            "by_branch":     by_branch,
            "by_tramo_mora": by_tramo,
            "top_contracts": top_contracts,
            "evolution_30d": evolution,
        })
