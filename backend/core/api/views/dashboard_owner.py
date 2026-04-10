"""
Dashboard global del dueño — visión completa en un solo endpoint.
GET /api/dashboard/owner
"""
from decimal import Decimal
from datetime import date, timedelta

from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles


class OwnerDashboardView(APIView):
    """
    Snapshot global: contratos, caja, inventario, RRHH, MVI.
    Solo SUPERVISOR y OWNER_ADMIN.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        from core.models import (
            PawnContract, PawnPayment, CashMovement, CashSession, Branch,
        )
        from core.models_inventory import DirectPurchase
        from core.models_mvi import AppraisalOverride

        today     = timezone.now().date()
        month_start = today.replace(day=1)

        # ── 1. Contratos ──────────────────────────────────────────────────────
        contracts_qs = PawnContract.objects.all()
        active_count = contracts_qs.filter(status="ACTIVE").count()

        # Vencidos (due_date < hoy, aún ACTIVE)
        overdue_count = contracts_qs.filter(
            status="ACTIVE", due_date__lt=today
        ).count()

        # Vencidos hace >5 días (EN_MORA)
        mora_threshold = today - timedelta(days=5)
        mora_count = contracts_qs.filter(
            status="ACTIVE", due_date__lt=mora_threshold
        ).count()

        # Elegibles para venta (>90 días sin actividad — aproximación por due_date)
        eligible_sale_date = today - timedelta(days=90)
        eligible_sale_count = contracts_qs.filter(
            status="ACTIVE", due_date__lt=eligible_sale_date
        ).count()

        # Capital total prestado (contratos activos)
        capital_active = contracts_qs.filter(status="ACTIVE").aggregate(
            total=Sum("principal_amount")
        )["total"] or Decimal("0")

        # Contratos cerrados este mes
        closed_month = contracts_qs.filter(
            status="CLOSED",
        ).count()

        # ── 2. Flujo de caja (mes actual) ─────────────────────────────────────
        movements_month = CashMovement.objects.filter(
            performed_at__date__gte=month_start
        )

        loans_out_month = movements_month.filter(
            movement_type="LOAN_OUT"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        payments_in_month = movements_month.filter(
            movement_type="PAYMENT_IN"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        expenses_month = movements_month.filter(
            movement_type="EXPENSE"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        purchases_out_month = movements_month.filter(
            movement_type="PURCHASE_OUT"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        net_flow = payments_in_month - loans_out_month - expenses_month - purchases_out_month

        # ── 3. Inventario Compra Directa ───────────────────────────────────────
        inv_qs = DirectPurchase.objects.all()

        inv_pending   = inv_qs.filter(status="COMPRADO_PENDIENTE").count()
        inv_for_sale  = inv_qs.filter(status="EN_VENTA").count()
        inv_sold_month = inv_qs.filter(
            status="VENDIDO", sold_at__date__gte=month_start
        ).count()

        inv_capital_exposed = inv_qs.filter(
            status__in=["COMPRADO_PENDIENTE", "EN_VENTA"]
        ).aggregate(total=Sum("purchase_price"))["total"] or Decimal("0")

        inv_revenue_month = inv_qs.filter(
            status="VENDIDO", sold_at__date__gte=month_start
        ).aggregate(total=Sum("sale_price"))["total"] or Decimal("0")

        inv_profit_month = inv_qs.filter(
            status="VENDIDO", sold_at__date__gte=month_start
        ).aggregate(total=Sum("actual_profit"))["total"] or Decimal("0")

        # ── 4. MVI — overrides pendientes ─────────────────────────────────────
        mvi_pending   = AppraisalOverride.objects.filter(status="PENDING").count()
        mvi_approved_month = AppraisalOverride.objects.filter(
            status="APPROVED", authorized_at__date__gte=month_start
        ).count()

        # ── 5. Por sucursal — Fix #9: aggregates batch en vez de N queries por sucursal
        # Un solo query por métrica, agrupado por branch
        active_by_branch = {
            r["branch_id"]: r["cnt"]
            for r in contracts_qs.filter(status="ACTIVE")
            .values("branch_id").annotate(cnt=Count("id"))
        }
        overdue_by_branch = {
            r["branch_id"]: r["cnt"]
            for r in contracts_qs.filter(status="ACTIVE", due_date__lt=today)
            .values("branch_id").annotate(cnt=Count("id"))
        }
        capital_by_branch = {
            r["branch_id"]: r["total"] or Decimal("0")
            for r in contracts_qs.filter(status="ACTIVE")
            .values("branch_id").annotate(total=Sum("principal_amount"))
        }
        payments_by_branch = {
            r["branch_id"]: r["total"] or Decimal("0")
            for r in CashMovement.objects.filter(
                movement_type="PAYMENT_IN", performed_at__date__gte=month_start
            ).values("branch_id").annotate(total=Sum("amount"))
        }

        branches_data = []
        for branch in Branch.objects.all().order_by("code"):
            branches_data.append({
                "branch_code":       branch.code,
                "branch_name":       branch.name,
                "active_contracts":  active_by_branch.get(branch.id, 0),
                "overdue_contracts": overdue_by_branch.get(branch.id, 0),
                "capital_deployed":  str(capital_by_branch.get(branch.id, Decimal("0"))),
                "payments_month":    str(payments_by_branch.get(branch.id, Decimal("0"))),
            })

        return Response({
            "as_of": str(today),
            "month": str(month_start),
            "contracts": {
                "active":         active_count,
                "overdue":        overdue_count,
                "en_mora":        mora_count,
                "eligible_sale":  eligible_sale_count,
                "closed_month":   closed_month,
                "capital_deployed": str(capital_active),
            },
            "cash_flow_month": {
                "loans_disbursed":   str(loans_out_month),
                "payments_received": str(payments_in_month),
                "expenses":          str(expenses_month),
                "purchases_paid":    str(purchases_out_month),
                "net_flow":          str(net_flow),
            },
            "inventory": {
                "pending_pricing":   inv_pending,
                "for_sale":          inv_for_sale,
                "sold_this_month":   inv_sold_month,
                "capital_exposed":   str(inv_capital_exposed),
                "revenue_month":     str(inv_revenue_month),
                "profit_month":      str(inv_profit_month),
            },
            "mvi": {
                "overrides_pending":       mvi_pending,
                "overrides_approved_month": mvi_approved_month,
            },
            "by_branch": branches_data,
        })
