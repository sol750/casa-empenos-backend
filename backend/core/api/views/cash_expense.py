"""
Gastos Operativos (G) y Compras Directas (CD)
==============================================
POST /api/cash-sessions/<session_id>/expenses     → Registrar gasto G
GET  /api/cash-sessions/<session_id>/expenses     → Listar gastos de la sesión

POST /api/cash-sessions/<session_id>/purchases    → Registrar compra directa CD
GET  /api/cash-sessions/<session_id>/purchases    → Listar compras de la sesión
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers, status

from core.models import CashSession, CashMovement, CashExpense
from core.api.security import require_roles
from core.services.cash_alerts import check_balance_thresholds


# ── Serializer para Gasto (G) ─────────────────────────────────────────────────
class CashExpenseCreateSerializer(serializers.Serializer):
    amount         = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    category       = serializers.ChoiceField(choices=CashExpense.Category.choices, default="OTHER")
    description    = serializers.CharField(min_length=5, max_length=500)
    receipt        = serializers.ImageField(required=False, allow_null=True)
    note           = serializers.CharField(required=False, default="", allow_blank=True)
    effective_date = serializers.DateField(required=False, allow_null=True, default=None)

    def validate_effective_date(self, value):
        if value and value > timezone.now().date():
            raise serializers.ValidationError("effective_date no puede ser futura.")
        return value


# ── Serializer para Compra Directa (CD) ──────────────────────────────────────
class CashPurchaseCreateSerializer(serializers.Serializer):
    amount         = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    description    = serializers.CharField(min_length=3, max_length=300)
    note           = serializers.CharField(required=False, default="", allow_blank=True)
    effective_date = serializers.DateField(required=False, allow_null=True, default=None)

    def validate_effective_date(self, value):
        if value and value > timezone.now().date():
            raise serializers.ValidationError("effective_date no puede ser futura.")
        return value


def _get_open_session(session_id):
    try:
        s = CashSession.objects.select_related("cash_register", "branch").get(
            public_id=session_id
        )
        return s
    except CashSession.DoesNotExist:
        return None


# ─────────────────────────────────────────────────────────────────────────────
class CashExpenseView(APIView):
    """
    POST /api/cash-sessions/<session_id>/expenses
    GET  /api/cash-sessions/<session_id>/expenses
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        session = _get_open_session(session_id)
        if not session:
            return Response({"detail": "Sesión no encontrada."}, status=404)

        movements = session.movements.filter(
            movement_type=CashMovement.MovementType.EXPENSE_OUT
        ).select_related("expense_detail").order_by("performed_at")

        expenses = []
        for m in movements:
            detail = getattr(m, "expense_detail", None)
            expenses.append({
                "public_id":   str(m.public_id),
                "amount":      str(m.amount),
                "performed_at": m.performed_at,
                "note":        m.note,
                "category":    detail.category    if detail else None,
                "description": detail.description if detail else "",
                "receipt_url": (
                    request.build_absolute_uri(detail.receipt.url)
                    if detail and detail.receipt else None
                ),
            })

        return Response({"expenses": expenses, "total": len(expenses)})

    def post(self, request, session_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        session = _get_open_session(session_id)
        if not session:
            return Response({"detail": "Sesión no encontrada."}, status=404)
        if session.status != CashSession.Status.OPEN:
            return Response({"detail": "La sesión no está abierta."}, status=409)

        ser = CashExpenseCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data

        with transaction.atomic():
            movement = CashMovement.objects.create(
                cash_session   = session,
                cash_register  = session.cash_register,
                branch         = session.branch,
                movement_type  = CashMovement.MovementType.EXPENSE_OUT,
                amount         = v["amount"],
                performed_by   = request.user,
                note           = v.get("note", "") or f"G: {v['description'][:60]}",
                effective_date = v.get("effective_date"),
            )
            expense = CashExpense.objects.create(
                cash_movement = movement,
                category      = v["category"],
                description   = v["description"],
                receipt       = v.get("receipt"),
            )

        # Verificar umbrales tras el egreso
        threshold_check = check_balance_thresholds(session)

        return Response({
            "movement_id":  str(movement.public_id),
            "amount":       str(movement.amount),
            "category":     expense.category,
            "description":  expense.description,
            "performed_at": movement.performed_at,
            "balance_after": threshold_check["balance"],
            "alerts":       threshold_check["alerts"],
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
class CashPurchaseView(APIView):
    """
    POST /api/cash-sessions/<session_id>/purchases   → CD Compra Directa
    GET  /api/cash-sessions/<session_id>/purchases
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        session = _get_open_session(session_id)
        if not session:
            return Response({"detail": "Sesión no encontrada."}, status=404)

        movements = session.movements.filter(
            movement_type=CashMovement.MovementType.PURCHASE_OUT
        ).order_by("performed_at")

        return Response({
            "purchases": [
                {
                    "public_id":   str(m.public_id),
                    "amount":      str(m.amount),
                    "description": m.note,
                    "performed_at": m.performed_at,
                    "performed_by": m.performed_by.username,
                }
                for m in movements
            ]
        })

    def post(self, request, session_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        session = _get_open_session(session_id)
        if not session:
            return Response({"detail": "Sesión no encontrada."}, status=404)
        if session.status != CashSession.Status.OPEN:
            return Response({"detail": "La sesión no está abierta."}, status=409)

        ser = CashPurchaseCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data

        # Validar saldo mínimo antes de procesar
        balance_before = session.expected_balance
        if balance_before - v["amount"] < session.cash_register.min_balance:
            return Response({
                "detail": (
                    f"Fondos insuficientes. El saldo después de la compra "
                    f"(Bs.{balance_before - v['amount']:,.2f}) quedaría por debajo "
                    f"del mínimo operativo (Bs.{session.cash_register.min_balance:,.2f})."
                ),
                "balance": str(balance_before),
                "min_balance": str(session.cash_register.min_balance),
            }, status=400)

        with transaction.atomic():
            movement = CashMovement.objects.create(
                cash_session   = session,
                cash_register  = session.cash_register,
                branch         = session.branch,
                movement_type  = CashMovement.MovementType.PURCHASE_OUT,
                amount         = v["amount"],
                performed_by   = request.user,
                note           = f"CD: {v['description'][:80]}",
                effective_date = v.get("effective_date"),
            )

        threshold_check = check_balance_thresholds(session)

        return Response({
            "movement_id":   str(movement.public_id),
            "amount":        str(movement.amount),
            "description":   v["description"],
            "performed_at":  movement.performed_at,
            "balance_after": threshold_check["balance"],
            "alerts":        threshold_check["alerts"],
        }, status=status.HTTP_201_CREATED)
