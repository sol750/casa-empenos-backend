"""
Rentabilidad del Dueño — GET /api/owner/profitability
======================================================
Utilidades desglosadas por fuente, período y sucursal.

Fuentes de utilidad:
  UC  — Utilidad de Contratos (intereses cobrados en pagos y renovaciones)
  UV  — Utilidad de Ventas (margen en compras directas vendidas)
  UT  — Utilidad Total = UC + UV

Deducciones:
  UNI — Utilidad Neta Inversionistas (% que corresponde a inversores)
  G   — Gastos operativos (EXPENSE_OUT)
  UN  — Utilidad Neta del Dueño = UT − UNI − G

Parámetros:
  ?from=YYYY-MM-DD  (default: inicio del mes actual)
  ?to=YYYY-MM-DD    (default: hoy)
  ?branch=SUC-01    (default: todas)
"""
from decimal import Decimal
from datetime import date

from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models import (
    PawnPayment, PawnRenewal, PawnAmortization, PawnContract,
    CashMovement, Investor, InvestorMovement,
)
from core.models_inventory import DirectPurchase


def _parse_range(request):
    today = timezone.now().date()
    month_start = today.replace(day=1)

    try:
        from_date = date.fromisoformat(request.query_params.get("from", str(month_start)))
    except ValueError:
        from_date = month_start

    try:
        to_date = date.fromisoformat(request.query_params.get("to", str(today)))
    except ValueError:
        to_date = today

    return from_date, to_date


def _zero():
    return Decimal("0.00")


class OwnerProfitabilityView(APIView):
    """
    GET /api/owner/profitability
    Utilidades del período con todo el desglose.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        from_date, to_date = _parse_range(request)
        branch_code = request.query_params.get("branch", "").upper() or None

        # ── 1. UC — UTILIDAD DE CONTRATOS ─────────────────────────────────────
        # 1a. Interés cobrado en pagos normales
        payments_qs = PawnPayment.objects.filter(
            paid_at__date__gte=from_date,
            paid_at__date__lte=to_date,
        )
        if branch_code:
            payments_qs = payments_qs.filter(contract__branch__code=branch_code)

        uc_payments = payments_qs.aggregate(
            interest=Sum("interest_paid"),
            principal=Sum("principal_paid"),
            total=Sum("amount"),
        )
        uc_interest_payments  = uc_payments["interest"]  or _zero()
        uc_principal_payments = uc_payments["principal"] or _zero()

        # 1b. Interés cobrado en renovaciones
        renewals_qs = PawnRenewal.objects.filter(
            renewed_at__date__gte=from_date,
            renewed_at__date__lte=to_date,
        )
        if branch_code:
            renewals_qs = renewals_qs.filter(contract__branch__code=branch_code)

        uc_renewals = renewals_qs.aggregate(
            interest=Sum("interest_charged"),
            fee=Sum("fee_charged"),
            total=Sum("amount_charged"),
        )
        uc_interest_renewals = uc_renewals["interest"] or _zero()
        uc_fee_renewals      = uc_renewals["fee"]      or _zero()

        # 1c. Interés cobrado en amortizaciones
        amort_qs = PawnAmortization.objects.filter(
            performed_at__date__gte=from_date,
            performed_at__date__lte=to_date,
        )
        if branch_code:
            amort_qs = amort_qs.filter(contract__branch__code=branch_code)

        uc_amort = amort_qs.aggregate(interest=Sum("interest_paid"))
        uc_interest_amort = uc_amort["interest"] or _zero()

        uc_total_interest = uc_interest_payments + uc_interest_renewals + uc_interest_amort
        uc_total_fees     = uc_fee_renewals
        uc_total          = uc_total_interest + uc_total_fees

        # ── 2. UC DESGLOSADA POR SUCURSAL ─────────────────────────────────────
        from core.models import Branch
        uc_by_branch = []
        for branch in Branch.objects.filter(is_active=True).order_by("code"):
            bp = PawnPayment.objects.filter(
                paid_at__date__gte=from_date,
                paid_at__date__lte=to_date,
                contract__branch=branch,
            ).aggregate(interest=Sum("interest_paid"))
            br = PawnRenewal.objects.filter(
                renewed_at__date__gte=from_date,
                renewed_at__date__lte=to_date,
                contract__branch=branch,
            ).aggregate(interest=Sum("interest_charged"), fee=Sum("fee_charged"))
            ba = PawnAmortization.objects.filter(
                performed_at__date__gte=from_date,
                performed_at__date__lte=to_date,
                contract__branch=branch,
            ).aggregate(interest=Sum("interest_paid"))

            branch_uc = (
                (bp["interest"] or _zero()) +
                (br["interest"] or _zero()) +
                (br["fee"]      or _zero()) +
                (ba["interest"] or _zero())
            )
            uc_by_branch.append({"branch_code": branch.code, "uc": str(branch_uc)})

        # ── 3. UV — UTILIDAD DE VENTAS (Compra Directa) ───────────────────────
        sales_qs = DirectPurchase.objects.filter(
            status="VENDIDO",
            sold_at__date__gte=from_date,
            sold_at__date__lte=to_date,
        )
        if branch_code:
            sales_qs = sales_qs.filter(branch__code=branch_code)

        uv_agg = sales_qs.aggregate(
            total_sale=Sum("sale_price"),
            total_cost=Sum("purchase_price"),
            total_profit=Sum("actual_profit"),
            count=Sum("id") if False else None,  # placeholder
        )
        # count manual
        uv_count       = sales_qs.count()
        uv_sale_total  = uv_agg["total_sale"]   or _zero()
        uv_cost_total  = uv_agg["total_cost"]   or _zero()
        uv_profit      = uv_agg["total_profit"] or _zero()

        # Por categoría
        uv_by_category = []
        for row in (
            sales_qs.values("category")
            .annotate(profit=Sum("actual_profit"), count=Sum("id") if False else None)
            .order_by("-profit")
        ):
            cat_count = sales_qs.filter(category=row["category"]).count()
            uv_by_category.append({
                "category": row["category"],
                "profit":   str(row["profit"] or _zero()),
                "count":    cat_count,
            })

        # ── 4. GASTOS OPERATIVOS ──────────────────────────────────────────────
        expenses_qs = CashMovement.objects.filter(
            movement_type="EXPENSE_OUT",
            performed_at__date__gte=from_date,
            performed_at__date__lte=to_date,
        )
        if branch_code:
            expenses_qs = expenses_qs.filter(branch__code=branch_code)

        total_expenses = expenses_qs.aggregate(t=Sum("amount"))["t"] or _zero()

        # Gastos por categoría (via CashExpense relacionado)
        expenses_by_category = []
        from core.models import CashExpense
        for row in (
            CashExpense.objects
            .filter(
                cash_movement__movement_type="EXPENSE_OUT",
                cash_movement__performed_at__date__gte=from_date,
                cash_movement__performed_at__date__lte=to_date,
            )
            .values("category")
            .annotate(total=Sum("cash_movement__amount"))
            .order_by("-total")
        ):
            expenses_by_category.append({
                "category": row["category"],
                "total":    str(row["total"] or _zero()),
            })

        # ── 5. UTILIDAD PARA INVERSIONISTAS ───────────────────────────────────
        # Interés generado por contratos de inversionistas en el período
        inv_contracts = PawnContract.objects.filter(
            investor__isnull=False
        ).values_list("id", "investor__profit_rate_pct")

        inv_contract_map = {cid: pct for cid, pct in inv_contracts}

        # Interés cobrado en pagos de contratos con inversor
        inv_interest_payments = _zero()
        for pay in PawnPayment.objects.filter(
            paid_at__date__gte=from_date,
            paid_at__date__lte=to_date,
            contract__investor__isnull=False,
        ).select_related("contract"):
            pct = inv_contract_map.get(pay.contract_id, Decimal("50.00"))
            inv_interest_payments += pay.interest_paid * pct / Decimal("100")

        # Interés en renovaciones con inversor
        inv_interest_renewals = _zero()
        for ren in PawnRenewal.objects.filter(
            renewed_at__date__gte=from_date,
            renewed_at__date__lte=to_date,
            contract__investor__isnull=False,
        ).select_related("contract"):
            pct = inv_contract_map.get(ren.contract_id, Decimal("50.00"))
            inv_interest_renewals += ren.interest_charged * pct / Decimal("100")

        # Interés en amortizaciones con inversor
        inv_interest_amort = _zero()
        for am in PawnAmortization.objects.filter(
            performed_at__date__gte=from_date,
            performed_at__date__lte=to_date,
            contract__investor__isnull=False,
        ).select_related("contract"):
            pct = inv_contract_map.get(am.contract_id, Decimal("50.00"))
            inv_interest_amort += am.interest_paid * pct / Decimal("100")

        total_investor_share = inv_interest_payments + inv_interest_renewals + inv_interest_amort

        # ── 6. TOTALES Y UTILIDAD NETA DEL DUEÑO ─────────────────────────────
        ut_total         = uc_total + uv_profit           # Utilidad Bruta Total
        un_owner         = ut_total - total_investor_share - total_expenses  # Neta del dueño

        # ── 7. EVOLUCIÓN DIARIA (para gráficas) ──────────────────────────────
        # Agrupa UC por día (solo pagos, para no saturar)
        daily_uc = []
        daily_rows = (
            PawnPayment.objects.filter(
                paid_at__date__gte=from_date,
                paid_at__date__lte=to_date,
            )
            .extra(select={"day": "DATE(paid_at)"})
            .values("day")
            .annotate(interest=Sum("interest_paid"))
            .order_by("day")
        )
        for row in daily_rows:
            daily_uc.append({
                "date":     str(row["day"]),
                "interest": str(row["interest"] or _zero()),
            })

        return Response({
            "period": {"from": str(from_date), "to": str(to_date)},
            "branch_filter": branch_code,

            # ── Utilidad de contratos (UC) ─────────────────────────────────
            "uc_contracts": {
                "total":              str(uc_total),
                "interest_payments":  str(uc_interest_payments),
                "interest_renewals":  str(uc_interest_renewals),
                "interest_amort":     str(uc_interest_amort),
                "fees_renewals":      str(uc_total_fees),
                "by_branch":          uc_by_branch,
            },

            # ── Utilidad de ventas CD (UV) ────────────────────────────────
            "uv_sales": {
                "total_profit":   str(uv_profit),
                "total_revenue":  str(uv_sale_total),
                "total_cost":     str(uv_cost_total),
                "items_sold":     uv_count,
                "by_category":    uv_by_category,
            },

            # ── Gastos operativos (G) ─────────────────────────────────────
            "expenses": {
                "total":       str(total_expenses),
                "by_category": expenses_by_category,
            },

            # ── Utilidad para inversionistas (UNI) ────────────────────────
            "investor_share": {
                "total":               str(total_investor_share),
                "from_payments":       str(inv_interest_payments),
                "from_renewals":       str(inv_interest_renewals),
                "from_amortizations":  str(inv_interest_amort),
            },

            # ── Resumen final ─────────────────────────────────────────────
            "summary": {
                "uc_total":             str(uc_total),
                "uv_total":             str(uv_profit),
                "ut_gross":             str(ut_total),
                "investor_share":       str(total_investor_share),
                "expenses":             str(total_expenses),
                "un_owner_net":         str(un_owner),
            },

            # ── Evolución diaria ──────────────────────────────────────────
            "daily_interest": daily_uc,
        })
