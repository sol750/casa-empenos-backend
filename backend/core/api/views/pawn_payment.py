from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PawnContract, PawnPayment, CashSession, CashMovement
from core.api.serializers.pawn_payment import PawnPaymentCreateSerializer
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes
from core.services.interest_calc import fixed_interest
from core.services.scoring_engine import apply_contract_closure_score
from core.services.contract_state import get_contract_state


class PawnPaymentCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PawnPaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        # 1) Cargar sesión
        try:
            cash_session = CashSession.objects.select_related("cash_register", "branch").get(
                public_id=serializer.validated_data["cash_session_id"]
            )
        except CashSession.DoesNotExist:
            return Response({"detail": "Sesión de caja no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        if cash_session.status != CashSession.Status.OPEN:
            return Response({"detail": "La sesión de caja no está abierta."}, status=status.HTTP_409_CONFLICT)

        # 2) Cargar contrato
        try:
            contract = PawnContract.objects.select_related("branch").get(
                public_id=serializer.validated_data["pawn_contract_id"]
            )
        except PawnContract.DoesNotExist:
            return Response({"detail": "Contrato no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if contract.status != PawnContract.Status.ACTIVE:
            return Response({"detail": "El contrato no está activo."}, status=status.HTTP_409_CONFLICT)

        # 3) Acceso por rol — cualquier cajero de cualquier sucursal puede cobrar/cerrar
        # (La caja que recibe el dinero puede ser diferente a la del contrato)
        # Solo se bloquea si el usuario no tiene acceso a NINGUNA sucursal activa.
        if not is_owner_admin(request.user):
            allowed_codes = get_user_branch_codes(request.user)
            if not allowed_codes:
                return Response({"detail": "No tiene acceso a ninguna sucursal."}, status=status.HTTP_403_FORBIDDEN)

        payment_amount = serializer.validated_data["amount"]
        payment_date = serializer.validated_data.get("payment_date", timezone.now().date())
        note = serializer.validated_data.get("note", "")

        with transaction.atomic():
            # Bloquear contrato para cálculo concurrente correcto
            contract = PawnContract.objects.select_for_update().get(pk=contract.pk)

            totals = contract.payments.aggregate(principal_paid=Sum("principal_paid"))
            principal_paid_total = totals["principal_paid"] or Decimal("0.00")
            outstanding_principal = contract.principal_amount - principal_paid_total

            if outstanding_principal <= 0:
                return Response({"detail": "El contrato ya no tiene capital pendiente."}, status=status.HTTP_409_CONFLICT)

            # Interés mensual fijo sobre el capital pendiente.
            # Si el contrato tiene amortizaciones, el interés base es sobre el
            # capital ORIGINAL (el cliente ya pagó intereses en cada adenda).
            # En ambos casos: Capital × Tasa / 100 — sin prorrateo por días.
            interest_base = (
                contract.principal_amount
                if contract.amortizations.exists()
                else outstanding_principal
            )
            interest_due = fixed_interest(interest_base, contract.interest_rate_monthly)

            interest_paid = min(payment_amount, interest_due)
            remaining = payment_amount - interest_paid
            principal_paid = min(remaining, outstanding_principal)
            out_after = outstanding_principal - principal_paid

            payment = PawnPayment.objects.create(
                contract=contract,
                cash_session=cash_session,
                paid_by=request.user,
                amount=payment_amount,
                interest_paid=interest_paid,
                principal_paid=principal_paid,
                note=note,
            )

            # Movimiento de caja (entra dinero)
            CashMovement.objects.create(
                cash_session=cash_session,
                cash_register=cash_session.cash_register,
                branch=cash_session.branch,
                movement_type=CashMovement.MovementType.PAYMENT_IN,
                amount=payment_amount,
                performed_by=request.user,
                note=f"Pago contrato {contract.contract_number}",
            )

            # ── Actualizar contrato ───────────────────────────────────────────
            contract_was_open = contract.status == PawnContract.Status.ACTIVE
            if out_after <= 0:
                contract.status = PawnContract.Status.CLOSED

            if payment_date > from_date:
                contract.interest_accrued_until = payment_date

            contract.save(update_fields=["status", "interest_accrued_until"])

            # ── Disparar motor de scoring al cerrar el contrato ──────────────
            # Se ejecuta dentro del mismo atomic() para garantizar consistencia
            scoring_result = None
            if contract_was_open and contract.status == PawnContract.Status.CLOSED:
                scoring_result = apply_contract_closure_score(contract)

        response_data = {
            "pawn_payment_id":            str(payment.public_id),
            "contract_number":            contract.contract_number,
            "contract_status":            contract.status,
            "amount":                     str(payment.amount),
            "interest_paid":              str(payment.interest_paid),
            "principal_paid":             str(payment.principal_paid),
            "outstanding_principal_after": str(outstanding_principal - principal_paid),
        }

        # Adjuntar resultado del scoring si el contrato fue cerrado
        if scoring_result and scoring_result.get("applied"):
            response_data["scoring_update"] = {
                "customer_score_before": scoring_result["old_score"],
                "customer_score_after":  scoring_result["new_score"],
                "category_before":       scoring_result["old_category"],
                "category_after":        scoring_result["new_category"],
                "risk_color":            scoring_result["risk_color"],
                "days_late":             scoring_result["days_late"],
                "points_delta":          scoring_result["delta"],
            }

        return Response(response_data, status=status.HTTP_201_CREATED)
