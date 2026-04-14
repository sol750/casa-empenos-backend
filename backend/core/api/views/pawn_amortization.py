"""
Vistas de amortización de contratos de empeño.

GET  /api/pawn-contracts/{id}/amortize/preview?capital=500
     → Muestra montos sin guardar

POST /api/pawn-contracts/{id}/amortize
     → Ejecuta la amortización y genera la adenda

GET  /api/pawn-contracts/{id}/state
     → Estado en tiempo real + montos de recuperación
"""
from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PawnContract, CashSession
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes
from core.services.contract_state import get_contract_state, calculate_recovery_amount, ContractState
from core.services.pawn_amortization import calculate_amortization_preview, create_amortization


def _load_contract(contract_id, user):
    """Carga contrato y valida acceso. Retorna (contract, error_response)."""
    try:
        contract = PawnContract.objects.select_related("branch").prefetch_related(
            "payments", "renewals", "amortizations"
        ).get(public_id=contract_id)
    except PawnContract.DoesNotExist:
        return None, Response({"detail": "Contrato no encontrado."}, status=404)

    if not is_owner_admin(user):
        allowed = get_user_branch_codes(user)
        if contract.branch.code not in allowed:
            return None, Response({"detail": "Sin acceso a esta sucursal."}, status=403)

    return contract, None


class PawnContractStateView(APIView):
    """
    GET /api/pawn-contracts/{contract_id}/state
    Estado en tiempo real + montos de recuperación y amortización.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, contract_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        contract, err = _load_contract(contract_id, request.user)
        if err:
            return err

        recovery = calculate_recovery_amount(contract)

        data = {
            "contract_number":      contract.contract_number,
            "status_stored":        contract.status,
            "state":                recovery["state"],
            "due_date":             str(contract.due_date),
            "outstanding_principal": str(recovery["outstanding_principal"]),
            "interest_due":         str(recovery["interest_due"]),
            "total_to_recover":     str(recovery["total_to_recover"]),
            "can_amortize":         recovery["can_amortize"],
            "can_recover":          recovery["can_recover"],
        }

        return Response(data)


class PawnAmortizationPreviewView(APIView):
    """
    GET /api/pawn-contracts/{contract_id}/amortize/preview?capital=500
    Simula la amortización sin guardar nada.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, contract_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        contract, err = _load_contract(contract_id, request.user)
        if err:
            return err

        capital_str = request.query_params.get("capital")
        if not capital_str:
            return Response({"detail": "Parámetro requerido: ?capital=<monto>"}, status=400)

        try:
            capital = Decimal(capital_str)
        except InvalidOperation:
            return Response({"detail": "capital debe ser un número válido."}, status=400)

        try:
            preview = calculate_amortization_preview(contract, capital)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        return Response({
            "contract_number":      contract.contract_number,
            "state":                preview["state"],
            "outstanding_principal": str(preview["outstanding_principal"]),
            "interest_due":         str(preview["interest_due"]),
            "capital_to_pay":       str(preview["capital_to_pay"]),
            "total_to_pay":         str(preview["total_to_pay"]),
            "new_principal":        str(preview["new_principal"]),
            "previous_due_date":    str(preview["previous_due_date"]),
            "new_due_date":         str(preview["new_due_date"]),
            "interest_rate_monthly": str(preview["interest_rate_monthly"]),
        })


class PawnAmortizationCreateView(APIView):
    """
    POST /api/pawn-contracts/{contract_id}/amortize
    Body: { "cash_session_id": "uuid", "capital_to_pay": 500, "note": "" }
    Ejecuta la amortización y devuelve la adenda.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, contract_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        contract, err = _load_contract(contract_id, request.user)
        if err:
            return err

        capital_raw = request.data.get("capital_to_pay")
        if capital_raw is None:
            return Response({"detail": "Se requiere capital_to_pay."}, status=400)

        try:
            capital = Decimal(str(capital_raw))
        except InvalidOperation:
            return Response({"detail": "capital_to_pay debe ser un número válido."}, status=400)

        cash_session_id = request.data.get("cash_session_id")
        if not cash_session_id:
            return Response({"detail": "Se requiere cash_session_id."}, status=400)

        try:
            cash_session = CashSession.objects.select_related("cash_register", "branch").get(
                public_id=cash_session_id
            )
        except CashSession.DoesNotExist:
            return Response({"detail": "Sesión de caja no encontrada."}, status=404)

        if cash_session.status != CashSession.Status.OPEN:
            return Response({"detail": "La sesión de caja no está abierta."}, status=409)

        # Cualquier cajero con sesión activa puede amortizar contratos de otras sucursales

        note = request.data.get("note", "")

        try:
            amort, preview = create_amortization(contract, capital, cash_session, request.user, note)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(
            {
                "detail": "Amortización registrada. Se generó una adenda al contrato.",
                "amortization_id":      str(amort.public_id),
                "contract_number":      contract.contract_number,
                "addendum_number":      contract.amortizations.count(),
                "interest_paid":        str(preview["interest_due"]),
                "capital_paid":         str(preview["capital_to_pay"]),
                "total_paid":           str(preview["total_to_pay"]),
                "outstanding_before":   str(preview["outstanding_principal"]),
                "new_principal":        str(preview["new_principal"]),
                "previous_due_date":    str(preview["previous_due_date"]),
                "new_due_date":         str(preview["new_due_date"]),
                "performed_at":         amort.performed_at,
            },
            status=status.HTTP_201_CREATED,
        )
