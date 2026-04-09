"""
Estado de Cuenta del Inversionista
=====================================
GET /api/investors/<investor_id>/account

Estructura de respuesta:
  identity            → datos del inversionista
  financial_summary   → capital desplegado, en la calle, recuperado, utilidades
  active_contracts    → detalle de contratos ACTIVE (capital en riesgo)
  closed_contracts    → detalle de contratos CLOSED (rendimiento realizado)
  defaulted_contracts → detalle de contratos DEFAULTED (pérdidas potenciales)
  ledger              → movimientos InvestorMovement registrados

Cálculos clave:
  - capital_deployed  = suma principal de TODOS los contratos del inversor
  - capital_at_risk   = suma principal de contratos ACTIVE
  - capital_recovered = suma principal_paid de pagos sobre contratos CLOSED
  - interest_collected= suma interest_paid de TODOS los pagos
  - investor_profit   = interest_collected × (profit_rate_pct / 100)
  - interest_pending  = interés proyectado sobre contratos ACTIVE aún no cobrado
"""
from datetime import date
from decimal import Decimal

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models import Investor, PawnContract, PawnPayment


def _projected_interest(contract) -> Decimal:
    """
    Calcula el interés que generaría el contrato ACTIVE si se paga hoy.
    Fórmula: principal × rate_monthly × days_remaining / 30
    (si ya venció, usa days_overdue como referencia)
    """
    today = date.today()
    start = contract.start_date
    end   = max(contract.due_date, today)
    days  = (end - start).days or 1
    monthly_rate = contract.interest_rate_monthly / Decimal("100")
    return (contract.principal_amount * monthly_rate * Decimal(days) / Decimal("30")).quantize(
        Decimal("0.01")
    )


class InvestorAccountView(APIView):
    """
    GET /api/investors/<investor_id>/account
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, investor_id):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        try:
            investor = Investor.objects.get(public_id=investor_id)
        except Investor.DoesNotExist:
            return Response({"detail": "Inversionista no encontrado."}, status=404)

        # ── Contratos por estado ──────────────────────────────────────────────
        all_contracts = list(
            investor.contracts
            .select_related("branch", "customer")
            .prefetch_related("payments", "items")
            .order_by("-created_at")
        )

        active_contracts    = [c for c in all_contracts if c.status == PawnContract.Status.ACTIVE]
        closed_contracts    = [c for c in all_contracts if c.status == PawnContract.Status.CLOSED]
        defaulted_contracts = [c for c in all_contracts if c.status == PawnContract.Status.DEFAULTED]

        today = date.today()

        # ── Cálculos financieros ──────────────────────────────────────────────
        def sum_payments(contracts, field):
            return sum(
                getattr(p, field)
                for c in contracts
                for p in c.payments.all()
            )

        capital_deployed  = sum(c.principal_amount for c in all_contracts)
        capital_at_risk   = sum(c.principal_amount for c in active_contracts)
        capital_recovered = sum_payments(closed_contracts, "principal_paid")
        capital_lost      = sum(c.principal_amount for c in defaulted_contracts)  # en riesgo alto

        interest_collected = sum_payments(all_contracts, "interest_paid")
        investor_profit    = (interest_collected * investor.profit_rate_pct / Decimal("100")).quantize(
            Decimal("0.01")
        )
        house_profit = (interest_collected - investor_profit).quantize(Decimal("0.01"))

        # Interés proyectado en contratos activos
        interest_pending = sum(_projected_interest(c) for c in active_contracts)
        investor_profit_pending = (
            interest_pending * investor.profit_rate_pct / Decimal("100")
        ).quantize(Decimal("0.01"))

        # ── Serializar contratos ──────────────────────────────────────────────
        def serialize_contract(c, include_payments=True):
            payments_data = [
                {
                    "paid_at":        p.paid_at.isoformat(),
                    "amount":         str(p.amount),
                    "interest_paid":  str(p.interest_paid),
                    "principal_paid": str(p.principal_paid),
                }
                for p in c.payments.all()
            ] if include_payments else []

            total_interest = sum(p.interest_paid for p in c.payments.all())
            investor_cut   = (
                total_interest * investor.profit_rate_pct / Decimal("100")
            ).quantize(Decimal("0.01"))

            days_od = max(0, (today - c.due_date).days)

            return {
                "contract_number":   c.contract_number,
                "public_id":         str(c.public_id),
                "branch":            c.branch.code,
                "customer_name":     c.customer.full_name if c.customer else c.customer_full_name,
                "principal_amount":  str(c.principal_amount),
                "interest_rate":     str(c.interest_rate_monthly),
                "start_date":        str(c.start_date),
                "due_date":          str(c.due_date),
                "status":            c.status,
                "days_overdue":      days_od if c.status != PawnContract.Status.ACTIVE else None,
                "interest_collected": str(total_interest),
                "investor_cut":       str(investor_cut),
                "payments":          payments_data,
            }

        # ── Ledger de movimientos del inversionista ───────────────────────────
        ledger_qs = investor.movements.select_related("related_contract").order_by("-created_at")[:50]
        ledger = [
            {
                "movement_type":     m.movement_type,
                "amount":            str(m.amount),
                "related_contract":  m.related_contract.contract_number if m.related_contract else None,
                "note":              m.note,
                "created_at":        m.created_at.isoformat(),
            }
            for m in ledger_qs
        ]

        return Response({
            "identity": {
                "investor_id":      str(investor.public_id),
                "full_name":        investor.full_name,
                "ci":               investor.ci,
                "profit_rate_pct":  str(investor.profit_rate_pct),
                "member_since":     investor.created_at.date().isoformat(),
            },
            "financial_summary": {
                # Capital
                "capital_deployed":         str(capital_deployed),
                "capital_at_risk":          str(capital_at_risk),
                "capital_recovered":        str(capital_recovered),
                "capital_lost_defaulted":   str(capital_lost),
                # Utilidades realizadas
                "interest_collected":       str(interest_collected),
                "investor_profit":          str(investor_profit),
                "house_profit":             str(house_profit),
                # Utilidades proyectadas (activos)
                "interest_pending":         str(interest_pending),
                "investor_profit_pending":  str(investor_profit_pending),
                # Contratos
                "total_contracts":          len(all_contracts),
                "active_count":             len(active_contracts),
                "closed_count":             len(closed_contracts),
                "defaulted_count":          len(defaulted_contracts),
            },
            "active_contracts": [
                serialize_contract(c, include_payments=False) for c in active_contracts
            ],
            "closed_contracts": [
                serialize_contract(c, include_payments=True) for c in closed_contracts
            ],
            "defaulted_contracts": [
                serialize_contract(c, include_payments=True) for c in defaulted_contracts
            ],
            "ledger": ledger,
        })
