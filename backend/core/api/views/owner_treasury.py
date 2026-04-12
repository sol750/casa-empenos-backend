"""
Tesoro del Dueño — GET /api/owner/treasury
===========================================
Vista maestra del capital: cuánto hay, de dónde viene, dónde está.

Secciones:
  1. capital_position   — balance total por caja + tipo de origen
  2. capital_deployed   — cuánto está en contratos activos (en la calle)
  3. investor_capital   — capital de inversionistas dentro del sistema
  4. own_capital        — capital propio neto (total - inversionistas)
  5. cash_by_register   — saldo real en cada caja ahora mismo
  6. movements_today    — flujo del día actual

Parámetros:
  ?date=YYYY-MM-DD  — snapshot de cualquier fecha (default: hoy)
"""
from decimal import Decimal
from datetime import date

from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models import (
    CashRegister, CashSession, CashMovement,
    PawnContract, PawnPayment, Investor, InvestorAccount, InvestorMovement,
)
from core.models_inventory import DirectPurchase
from core.services.contract_state import calculate_outstanding_principal


def _parse_date(request) -> date:
    raw = request.query_params.get("date")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return timezone.now().date()


def _zero() -> Decimal:
    return Decimal("0.00")


class OwnerTreasuryView(APIView):
    """
    GET /api/owner/treasury
    Posición de capital completa del dueño en un solo request.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        today = _parse_date(request)
        month_start = today.replace(day=1)

        # ── 1. SALDO EN CAJAS (snapshot en tiempo real) ───────────────────────
        registers = CashRegister.objects.filter(is_active=True).select_related("branch")
        cash_by_register = []
        total_cash_in_registers = _zero()

        for reg in registers.order_by("register_type", "name"):
            open_session = CashSession.objects.filter(
                cash_register=reg, status="OPEN"
            ).first()

            if open_session:
                balance = open_session.expected_balance
                session_id = str(open_session.public_id)
                opened_at = str(open_session.opened_at)
            else:
                # Sin sesión abierta: usar closing_counted_amount de la última sesión
                last_closed = CashSession.objects.filter(
                    cash_register=reg, status="CLOSED"
                ).order_by("-closed_at").first()
                balance = last_closed.closing_counted_amount if last_closed else _zero()
                session_id = None
                opened_at  = None

            total_cash_in_registers += balance
            cash_by_register.append({
                "register_id":   str(reg.public_id),
                "register_name": reg.name,
                "register_type": reg.register_type,
                "branch_code":   reg.branch.code if reg.branch else None,
                "balance":       str(balance),
                "session_open":  open_session is not None,
                "session_id":    session_id,
                "opened_at":     opened_at,
            })

        # ── 2. CAPITAL EN LA CALLE (contratos activos) ────────────────────────
        active_contracts = PawnContract.objects.filter(
            status__in=["ACTIVE", "DEFAULTED", "EN_VENTA"]
        ).select_related("branch", "investor")

        capital_deployed_own       = _zero()
        capital_deployed_investors = _zero()
        contracts_active_count     = 0

        for c in active_contracts:
            outstanding = calculate_outstanding_principal(c)
            contracts_active_count += 1
            if c.investor_id:
                capital_deployed_investors += outstanding
            else:
                capital_deployed_own += outstanding

        capital_deployed_total = capital_deployed_own + capital_deployed_investors

        # ── 3. CAPITAL DE INVERSIONISTAS ──────────────────────────────────────
        investors_data = []
        total_investor_capital = _zero()
        total_investor_balance = _zero()  # saldo libre (no asignado a contratos)

        for acc in InvestorAccount.objects.select_related("investor").all():
            inv = acc.investor
            # Capital total depositado por este inversor
            deposited = (
                InvestorMovement.objects.filter(
                    investor=inv, movement_type="DEPOSIT"
                ).aggregate(t=Sum("amount"))["t"] or _zero()
            )
            withdrawn = (
                InvestorMovement.objects.filter(
                    investor=inv, movement_type="WITHDRAW"
                ).aggregate(t=Sum("amount"))["t"] or _zero()
            )
            assigned = (
                InvestorMovement.objects.filter(
                    investor=inv, movement_type="ASSIGN"
                ).aggregate(t=Sum("amount"))["t"] or _zero()
            )
            returned = (
                InvestorMovement.objects.filter(
                    investor=inv, movement_type="RETURN"
                ).aggregate(t=Sum("amount"))["t"] or _zero()
            )
            profits_paid = (
                InvestorMovement.objects.filter(
                    investor=inv, movement_type="PROFIT"
                ).aggregate(t=Sum("amount"))["t"] or _zero()
            )
            contracts_count = PawnContract.objects.filter(
                investor=inv, status__in=["ACTIVE", "DEFAULTED"]
            ).count()

            total_investor_capital += deposited - withdrawn
            total_investor_balance += acc.balance

            investors_data.append({
                "investor_id":       str(inv.public_id),
                "full_name":         inv.full_name,
                "ci":                inv.ci,
                "profit_rate_pct":   str(inv.profit_rate_pct),
                "total_deposited":   str(deposited),
                "total_withdrawn":   str(withdrawn),
                "total_assigned":    str(assigned),
                "total_returned":    str(returned),
                "profits_paid":      str(profits_paid),
                "free_balance":      str(acc.balance),
                "active_contracts":  contracts_count,
            })

        # ── 4. CAPITAL PROPIO (inyecciones - retiros del dueño) ───────────────
        own_injected = (
            CashMovement.objects.filter(movement_type="CAPITAL_IN")
            .aggregate(t=Sum("amount"))["t"] or _zero()
        )
        own_withdrawn = (
            CashMovement.objects.filter(movement_type="CAPITAL_OUT")
            .aggregate(t=Sum("amount"))["t"] or _zero()
        )
        own_net_capital = own_injected - own_withdrawn

        # ── 5. FLUJO DEL DÍA ──────────────────────────────────────────────────
        today_movements = CashMovement.objects.filter(
            performed_at__date=today
        )

        def day_sum(*types):
            return (
                today_movements.filter(movement_type__in=types)
                .aggregate(t=Sum("amount"))["t"] or _zero()
            )

        today_loans_out      = day_sum("LOAN_OUT")
        today_payments_in    = day_sum("PAYMENT_IN")
        today_purchases_out  = day_sum("PURCHASE_OUT")
        today_expenses_out   = day_sum("EXPENSE_OUT")
        today_capital_in     = day_sum("CAPITAL_IN")
        today_capital_out    = day_sum("CAPITAL_OUT")

        # ── 6. INVENTARIO EN VITRINA (capital expuesto en CD) ─────────────────
        inv_exposed = (
            DirectPurchase.objects.filter(status__in=["COMPRADO_PENDIENTE", "EN_VENTA"])
            .aggregate(t=Sum("purchase_price"))["t"] or _zero()
        )
        inv_for_sale_count = DirectPurchase.objects.filter(status="EN_VENTA").count()
        inv_pending_count  = DirectPurchase.objects.filter(status="COMPRADO_PENDIENTE").count()

        # ── TOTAL GENERAL VISIBLE ─────────────────────────────────────────────
        # Dónde está todo el dinero del sistema
        total_system = total_cash_in_registers + capital_deployed_total + inv_exposed

        return Response({
            "as_of": str(today),

            # Resumen ejecutivo
            "summary": {
                "total_in_system":          str(total_system),
                "cash_in_registers":        str(total_cash_in_registers),
                "capital_in_contracts":     str(capital_deployed_total),
                "capital_in_inventory":     str(inv_exposed),
                "own_net_capital":          str(own_net_capital),
                "investor_capital_total":   str(total_investor_capital),
                "investor_free_balance":    str(total_investor_balance),
            },

            # Capital en contratos desglosado
            "capital_deployed": {
                "total":               str(capital_deployed_total),
                "own":                 str(capital_deployed_own),
                "investors":           str(capital_deployed_investors),
                "active_contracts":    contracts_active_count,
            },

            # Capital propio del dueño
            "own_capital": {
                "total_injected":  str(own_injected),
                "total_withdrawn": str(own_withdrawn),
                "net_capital":     str(own_net_capital),
            },

            # Inventario CD
            "inventory": {
                "capital_exposed":    str(inv_exposed),
                "pending_pricing":    inv_pending_count,
                "for_sale":           inv_for_sale_count,
            },

            # Saldo por caja
            "cash_by_register": cash_by_register,

            # Inversionistas
            "investors": investors_data,

            # Flujo del día
            "today_flow": {
                "date":           str(today),
                "loans_out":      str(today_loans_out),
                "payments_in":    str(today_payments_in),
                "purchases_out":  str(today_purchases_out),
                "expenses_out":   str(today_expenses_out),
                "capital_in":     str(today_capital_in),
                "capital_out":    str(today_capital_out),
                "net_operational": str(today_payments_in - today_loans_out - today_purchases_out - today_expenses_out),
            },
        })
