"""
Reporte de Concentración de Riesgo por Cliente
GET /api/reports/risk-concentration

Responde tres preguntas clave para el dueño e inversionistas:

  1. ¿Hay algún cliente con demasiados contratos activos?
  2. ¿Qué porcentaje de la cartera es de clientes ORO/PLATA/BRONCE?
  3. ¿Cuál es la tasa de recuperación y mora por segmento?

Este reporte es la base para mostrar la "salud" del negocio ante
nuevos inversionistas y detectar concentración de riesgo.
"""
from decimal import Decimal

from django.db.models import Sum, Count, Q, F
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Customer, PawnContract
from core.api.security import require_roles


class RiskConcentrationReportView(APIView):
    """
    Solo accesible para OWNER_ADMIN y SUPERVISOR.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        today = timezone.localdate()

        # ── 1. Totales de cartera ─────────────────────────────────────────────
        portfolio = PawnContract.objects.filter(status=PawnContract.Status.ACTIVE)

        portfolio_stats = portfolio.aggregate(
            total_principal = Sum("principal_amount"),
            total_contracts = Count("id"),
        )
        total_principal = portfolio_stats["total_principal"] or Decimal("0.00")
        total_contracts = portfolio_stats["total_contracts"] or 0

        overdue_contracts = portfolio.filter(due_date__lt=today).count()
        overdue_principal = portfolio.filter(due_date__lt=today).aggregate(
            s=Sum("principal_amount")
        )["s"] or Decimal("0.00")

        # ── 2. Concentración por cliente (top 10 por capital) ─────────────────
        top_clients = (
            PawnContract.objects
            .filter(status=PawnContract.Status.ACTIVE, customer__isnull=False)
            .values("customer__ci", "customer__first_name",
                    "customer__last_name_paternal", "customer__category",
                    "customer__score", "customer__risk_color")
            .annotate(
                contracts_count  = Count("id"),
                principal_total  = Sum("principal_amount"),
                overdue_count    = Count("id", filter=Q(due_date__lt=today)),
            )
            .order_by("-principal_total")[:10]
        )

        top_clients_list = []
        for row in top_clients:
            pct = (
                round(float(row["principal_total"]) / float(total_principal) * 100, 2)
                if total_principal > 0 else 0
            )
            # Alerta si un solo cliente concentra más del 20% de la cartera
            concentration_alert = pct > 20.0

            top_clients_list.append({
                "ci":               row["customer__ci"],
                "full_name":        f"{row['customer__first_name']} {row['customer__last_name_paternal']}",
                "category":         row["customer__category"],
                "score":            row["customer__score"],
                "risk_color":       row["customer__risk_color"],
                "contracts_count":  row["contracts_count"],
                "principal_total":  str(row["principal_total"]),
                "portfolio_pct":    pct,
                "overdue_count":    row["overdue_count"],
                "concentration_alert": concentration_alert,
            })

        # ── 3. Distribución por categoría (BRONCE / PLATA / ORO) ─────────────
        by_category = (
            PawnContract.objects
            .filter(status=PawnContract.Status.ACTIVE, customer__isnull=False)
            .values("customer__category")
            .annotate(
                contracts_count = Count("id"),
                principal_total = Sum("principal_amount"),
            )
            .order_by("customer__category")
        )

        category_breakdown = []
        for row in by_category:
            pct = (
                round(float(row["principal_total"]) / float(total_principal) * 100, 2)
                if total_principal > 0 else 0
            )
            category_breakdown.append({
                "category":        row["customer__category"],
                "contracts_count": row["contracts_count"],
                "principal_total": str(row["principal_total"]),
                "portfolio_pct":   pct,
            })

        # ── 4. Clientes fieles (ORO) — valor estratégico ──────────────────────
        oro_customers    = Customer.objects.filter(category="ORO").count()
        plata_customers  = Customer.objects.filter(category="PLATA").count()
        bronce_customers = Customer.objects.filter(category="BRONCE").count()
        total_customers  = Customer.objects.count()

        loyalty_overview = {
            "total_customers":  total_customers,
            "oro_count":        oro_customers,
            "plata_count":      plata_customers,
            "bronce_count":     bronce_customers,
            "oro_pct":          round(oro_customers / max(1, total_customers) * 100, 1),
            "blacklisted_count": Customer.objects.filter(is_blacklisted=True).count(),
        }

        # ── 5. Alertas globales ───────────────────────────────────────────────
        alerts = []
        if total_contracts > 0 and overdue_contracts / total_contracts > 0.15:
            alerts.append({
                "level": "HIGH",
                "message": f"Mora elevada: {overdue_contracts} contratos vencidos "
                           f"({round(overdue_contracts/total_contracts*100, 1)}% de la cartera).",
            })
        if top_clients_list and top_clients_list[0]["concentration_alert"]:
            alerts.append({
                "level": "MEDIUM",
                "message": (
                    f"Concentración de riesgo: el cliente "
                    f"{top_clients_list[0]['full_name']} representa "
                    f"{top_clients_list[0]['portfolio_pct']}% del capital total."
                ),
            })
        if loyalty_overview["oro_pct"] >= 20:
            alerts.append({
                "level": "INFO",
                "message": f"{loyalty_overview['oro_pct']}% de los clientes son ORO — cartera de alta calidad.",
            })

        return Response({
            "generated_at":   timezone.now(),
            "portfolio": {
                "total_contracts":  total_contracts,
                "total_principal":  str(total_principal),
                "overdue_contracts": overdue_contracts,
                "overdue_principal": str(overdue_principal),
                "overdue_rate_pct":  round(
                    overdue_contracts / max(1, total_contracts) * 100, 1
                ),
            },
            "top_clients_by_exposure": top_clients_list,
            "category_breakdown":      category_breakdown,
            "loyalty_overview":        loyalty_overview,
            "alerts":                  alerts,
        })
