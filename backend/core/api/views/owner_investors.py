"""
Estado de Cuenta de Inversionistas — /api/owner/investors/...
==============================================================
El dueño gestiona el ciclo completo de cada inversionista:
  GET  /api/owner/investors                   — lista todos los inversores
  GET  /api/owner/investors/{id}/statement    — estado de cuenta detallado
  POST /api/owner/investors/{id}/deposit      — el inversor deposita capital
  POST /api/owner/investors/{id}/profit       — registrar pago de utilidades al inversor
  POST /api/owner/investors/{id}/withdraw     — el inversor retira su capital
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.api.security import require_roles
from core.models import (
    Investor, InvestorAccount, InvestorMovement, PawnContract, PawnPayment,
    PawnRenewal, PawnAmortization, CashSession, CashMovement, CashRegister,
)


def _zero():
    return Decimal("0.00")


def _investor_or_404(investor_id):
    try:
        return Investor.objects.select_related("account").get(public_id=investor_id)
    except Investor.DoesNotExist:
        return None


def _build_statement(investor: Investor) -> dict:
    """Construye el estado de cuenta completo de un inversionista."""
    acc = investor.account

    # Movimientos del ledger
    movements_qs = InvestorMovement.objects.filter(
        investor=investor
    ).select_related("related_contract").order_by("-created_at")

    totals = movements_qs.aggregate(
        deposited  = Sum("amount", filter=Q(movement_type="DEPOSIT")),
        assigned   = Sum("amount", filter=Q(movement_type="ASSIGN")),
        returned   = Sum("amount", filter=Q(movement_type="RETURN")),
        profits    = Sum("amount", filter=Q(movement_type="PROFIT")),
        withdrawn  = Sum("amount", filter=Q(movement_type="WITHDRAW")),
    )
    deposited  = totals["deposited"]  or _zero()
    assigned   = totals["assigned"]   or _zero()
    returned   = totals["returned"]   or _zero()
    profits    = totals["profits"]    or _zero()
    withdrawn  = totals["withdrawn"]  or _zero()

    # Contratos activos de este inversor
    active_contracts = PawnContract.objects.filter(
        investor=investor, status__in=["ACTIVE", "DEFAULTED", "EN_VENTA"]
    ).select_related("branch")

    from core.services.contract_state import calculate_outstanding_principal
    capital_in_street = sum(
        calculate_outstanding_principal(c) for c in active_contracts
    )

    # Interés pendiente de pagar (generado pero no registrado como PROFIT aún)
    # = interés cobrado en contratos del inversor en todos los tiempos
    inv_contract_ids = list(
        PawnContract.objects.filter(investor=investor).values_list("id", flat=True)
    )
    pct = investor.profit_rate_pct / Decimal("100")

    interest_collected = _zero()
    for pay in PawnPayment.objects.filter(contract_id__in=inv_contract_ids):
        interest_collected += pay.interest_paid * pct
    for ren in PawnRenewal.objects.filter(contract_id__in=inv_contract_ids):
        interest_collected += ren.interest_charged * pct
    for am in PawnAmortization.objects.filter(contract_id__in=inv_contract_ids):
        interest_collected += am.interest_paid * pct

    interest_pending = interest_collected - profits  # lo que falta por pagarle

    # Historial de movimientos para el frontend
    ledger = []
    for m in movements_qs[:100]:
        ledger.append({
            "id":               str(m.id),
            "type":             m.movement_type,
            "amount":           str(m.amount),
            "note":             m.note,
            "created_at":       str(m.created_at),
            "contract_number":  m.related_contract.contract_number if m.related_contract else None,
        })

    # Contratos activos detalle
    contracts_detail = []
    for c in active_contracts.order_by("due_date"):
        outstanding = calculate_outstanding_principal(c)
        contracts_detail.append({
            "contract_number":  c.contract_number,
            "branch_code":      c.branch.code,
            "principal_amount": str(c.principal_amount),
            "outstanding":      str(outstanding),
            "due_date":         str(c.due_date),
            "status":           c.status,
        })

    return {
        "investor_id":     str(investor.public_id),
        "full_name":       investor.full_name,
        "ci":              investor.ci,
        "profit_rate_pct": str(investor.profit_rate_pct),

        "account": {
            "free_balance":         str(acc.balance),
            "capital_in_contracts": str(capital_in_street),
            "total_capital_active": str(acc.balance + Decimal(str(capital_in_street))),
        },

        "totals": {
            "deposited":           str(deposited),
            "withdrawn":           str(withdrawn),
            "net_deposited":       str(deposited - withdrawn),
            "assigned_to_contracts": str(assigned),
            "returned_from_contracts": str(returned),
            "interest_generated":  str(interest_collected),
            "profits_paid":        str(profits),
            "interest_pending":    str(max(interest_pending, _zero())),
        },

        "active_contracts_count": active_contracts.count(),
        "contracts":              contracts_detail,
        "ledger":                 ledger,
    }


# ─────────────────────────────────────────────────────────────────────────────
class OwnerInvestorListView(APIView):
    """GET /api/owner/investors — lista todos los inversores con resumen."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        results = []
        for inv in Investor.objects.select_related("account").order_by("full_name"):
            acc = inv.account
            active = PawnContract.objects.filter(
                investor=inv, status__in=["ACTIVE", "DEFAULTED"]
            ).count()
            results.append({
                "investor_id":     str(inv.public_id),
                "full_name":       inv.full_name,
                "ci":              inv.ci,
                "profit_rate_pct": str(inv.profit_rate_pct),
                "free_balance":    str(acc.balance),
                "active_contracts": active,
            })
        return Response({"count": len(results), "results": results})


# ─────────────────────────────────────────────────────────────────────────────
class OwnerInvestorStatementView(APIView):
    """GET /api/owner/investors/{id}/statement — estado de cuenta completo."""
    permission_classes = [IsAuthenticated]

    def get(self, request, investor_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        inv = _investor_or_404(investor_id)
        if not inv:
            return Response({"detail": "Inversionista no encontrado."}, status=404)
        return Response(_build_statement(inv))


# ─────────────────────────────────────────────────────────────────────────────
class OwnerInvestorDepositView(APIView):
    """
    POST /api/owner/investors/{id}/deposit
    El inversor deposita capital nuevo → InvestorMovement DEPOSIT
    y se suma al saldo libre (InvestorAccount.balance).

    Body: { "amount": 10000.00, "note": "Depósito inicial abril 2026",
            "cash_register_id": "<uuid>" }
    El cash_register_id indica en qué caja física entró el dinero
    (registra CashMovement CAPITAL_IN para cuadrar la caja).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, investor_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        inv = _investor_or_404(investor_id)
        if not inv:
            return Response({"detail": "Inversionista no encontrado."}, status=404)

        try:
            amount = Decimal(str(request.data.get("amount", 0)))
        except Exception:
            return Response({"detail": "'amount' decimal inválido."}, status=400)
        if amount <= 0:
            return Response({"detail": "El monto debe ser mayor a 0."}, status=400)

        note = request.data.get("note", "").strip() or f"Depósito de {inv.full_name}"
        register_id = request.data.get("cash_register_id")

        with transaction.atomic():
            acc = InvestorAccount.objects.select_for_update().get(investor=inv)
            acc.balance += amount
            acc.save(update_fields=["balance"])

            InvestorMovement.objects.create(
                investor=inv,
                amount=amount,
                movement_type=InvestorMovement.MovementType.DEPOSIT,
                note=note,
            )

            # Registrar entrada en caja física si se especificó
            if register_id:
                reg = CashRegister.objects.filter(public_id=register_id, is_active=True).first()
                if reg:
                    session = CashSession.objects.filter(
                        cash_register=reg, status="OPEN"
                    ).first()
                    if session:
                        CashMovement.objects.create(
                            cash_session  = session,
                            cash_register = reg,
                            branch        = reg.branch,
                            movement_type = CashMovement.MovementType.CAPITAL_IN,
                            amount        = amount,
                            performed_by  = request.user,
                            note          = f"Dep. inversionista: {inv.full_name} — {note}",
                        )

        return Response({
            "investor_id":    str(inv.public_id),
            "full_name":      inv.full_name,
            "amount":         str(amount),
            "new_balance":    str(acc.balance),
            "note":           note,
            "performed_at":   str(timezone.now()),
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
class OwnerInvestorProfitView(APIView):
    """
    POST /api/owner/investors/{id}/profit
    Registra el pago de utilidades al inversionista.
    Descuenta del saldo libre del inversor y registra PROFIT.

    Body: { "amount": 1500.00, "note": "Utilidades Q1 2026",
            "cash_register_id": "<uuid>" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, investor_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        inv = _investor_or_404(investor_id)
        if not inv:
            return Response({"detail": "Inversionista no encontrado."}, status=404)

        try:
            amount = Decimal(str(request.data.get("amount", 0)))
        except Exception:
            return Response({"detail": "'amount' decimal inválido."}, status=400)
        if amount <= 0:
            return Response({"detail": "El monto debe ser mayor a 0."}, status=400)

        note = request.data.get("note", "").strip() or f"Pago de utilidades a {inv.full_name}"
        register_id = request.data.get("cash_register_id")

        with transaction.atomic():
            acc = InvestorAccount.objects.select_for_update().get(investor=inv)

            InvestorMovement.objects.create(
                investor=inv,
                amount=amount,
                movement_type=InvestorMovement.MovementType.PROFIT,
                note=note,
            )

            # Salida de caja si se especificó
            if register_id:
                reg = CashRegister.objects.filter(public_id=register_id, is_active=True).first()
                if reg:
                    session = CashSession.objects.filter(
                        cash_register=reg, status="OPEN"
                    ).first()
                    if session:
                        CashMovement.objects.create(
                            cash_session  = session,
                            cash_register = reg,
                            branch        = reg.branch,
                            movement_type = CashMovement.MovementType.CAPITAL_OUT,
                            amount        = amount,
                            performed_by  = request.user,
                            note          = f"Pago utilidades: {inv.full_name} — {note}",
                        )

        return Response({
            "investor_id":  str(inv.public_id),
            "full_name":    inv.full_name,
            "amount_paid":  str(amount),
            "note":         note,
            "performed_at": str(timezone.now()),
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
class OwnerInvestorWithdrawView(APIView):
    """
    POST /api/owner/investors/{id}/withdraw
    El inversor retira parte o todo su capital libre.
    Descuenta de InvestorAccount.balance y registra WITHDRAW.

    Body: { "amount": 5000.00, "note": "Retiro parcial",
            "cash_register_id": "<uuid>" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, investor_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        inv = _investor_or_404(investor_id)
        if not inv:
            return Response({"detail": "Inversionista no encontrado."}, status=404)

        try:
            amount = Decimal(str(request.data.get("amount", 0)))
        except Exception:
            return Response({"detail": "'amount' decimal inválido."}, status=400)
        if amount <= 0:
            return Response({"detail": "El monto debe ser mayor a 0."}, status=400)

        note = request.data.get("note", "").strip() or f"Retiro de {inv.full_name}"
        register_id = request.data.get("cash_register_id")

        with transaction.atomic():
            acc = InvestorAccount.objects.select_for_update().get(investor=inv)
            if amount > acc.balance:
                return Response({
                    "detail": f"Saldo insuficiente. Disponible: {acc.balance} Bs.",
                    "available_balance": str(acc.balance),
                    "requested":         str(amount),
                }, status=status.HTTP_400_BAD_REQUEST)

            acc.balance -= amount
            acc.save(update_fields=["balance"])

            InvestorMovement.objects.create(
                investor=inv,
                amount=amount,
                movement_type=InvestorMovement.MovementType.WITHDRAW,
                note=note,
            )

            # Salida de caja si se especificó
            if register_id:
                reg = CashRegister.objects.filter(public_id=register_id, is_active=True).first()
                if reg:
                    session = CashSession.objects.filter(
                        cash_register=reg, status="OPEN"
                    ).first()
                    if session:
                        CashMovement.objects.create(
                            cash_session  = session,
                            cash_register = reg,
                            branch        = reg.branch,
                            movement_type = CashMovement.MovementType.CAPITAL_OUT,
                            amount        = amount,
                            performed_by  = request.user,
                            note          = f"Retiro inv.: {inv.full_name} — {note}",
                        )

        return Response({
            "investor_id":    str(inv.public_id),
            "full_name":      inv.full_name,
            "amount":         str(amount),
            "balance_before": str(acc.balance + amount),
            "new_balance":    str(acc.balance),
            "note":           note,
            "performed_at":   str(timezone.now()),
        }, status=status.HTTP_201_CREATED)
