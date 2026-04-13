"""
Módulo de Gestión de Sucursales y Cajas — OWNER_ADMIN exclusivo
================================================================
Permite crear y administrar la estructura física del negocio.

  GET    /api/branches                         — lista sucursales
  POST   /api/branches                         — crear sucursal
  GET    /api/branches/{branch_id}             — detalle de sucursal
  PATCH  /api/branches/{branch_id}             — actualizar sucursal
  POST   /api/branches/{branch_id}/cash-registers  — crear caja en esa sucursal
  GET    /api/cash-registers/{register_id}     — detalle de caja
  PATCH  /api/cash-registers/{register_id}/settings — actualizar config de caja

Solo OWNER_ADMIN puede ejecutar cualquier acción de este módulo.
"""
from decimal import Decimal, InvalidOperation

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models import Branch, CashRegister


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _branch_data(branch: Branch) -> dict:
    registers = branch.cash_registers.filter(is_active=True).order_by("register_type", "name")
    return {
        "branch_id":         branch.id,
        "name":              branch.name,
        "code":              branch.code,
        "is_active":         branch.is_active,
        "grace_period_days": branch.grace_period_days,
        "created_at":        str(branch.created_at),
        "cash_registers": [
            {
                "register_id":   str(r.public_id),
                "name":          r.name,
                "register_type": r.register_type,
                "is_active":     r.is_active,
                "min_balance":   str(r.min_balance),
                "max_balance":   str(r.max_balance),
            }
            for r in registers
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Sucursales
# ─────────────────────────────────────────────────────────────────────────────

class BranchListCreateView(APIView):
    """
    GET  /api/branches — lista todas las sucursales (activas e inactivas)
    POST /api/branches — crea una nueva sucursal

    Body POST:
    {
      "name": "Sucursal Centro",
      "code": "SC1",
      "grace_period_days": 30
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        branches = Branch.objects.prefetch_related("cash_registers").order_by("code")
        return Response({
            "count":   branches.count(),
            "results": [_branch_data(b) for b in branches],
        })

    def post(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})

        name = request.data.get("name", "").strip()
        code = request.data.get("code", "").strip().upper()
        grace = request.data.get("grace_period_days", 30)

        if not name:
            return Response({"detail": "'name' es requerido."}, status=400)
        if not code:
            return Response({"detail": "'code' es requerido."}, status=400)

        if Branch.objects.filter(code=code).exists():
            return Response(
                {"detail": f"Ya existe una sucursal con código '{code}'."},
                status=409,
            )

        try:
            grace = int(grace)
            if grace < 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "'grace_period_days' debe ser un entero >= 0."}, status=400)

        branch = Branch.objects.create(
            name=name,
            code=code,
            grace_period_days=grace,
            is_active=True,
        )

        return Response(_branch_data(branch), status=201)


class BranchDetailView(APIView):
    """
    GET   /api/branches/{branch_id} — detalle con sus cajas
    PATCH /api/branches/{branch_id} — actualizar nombre, gracia, estado activo

    Body PATCH (todos opcionales):
    {
      "name": "Nuevo nombre",
      "grace_period_days": 15,
      "is_active": false
    }
    """
    permission_classes = [IsAuthenticated]

    def _get_branch(self, branch_id):
        try:
            return Branch.objects.prefetch_related("cash_registers").get(id=branch_id)
        except Branch.DoesNotExist:
            return None

    def get(self, request, branch_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        branch = self._get_branch(branch_id)
        if not branch:
            return Response({"detail": "Sucursal no encontrada."}, status=404)
        return Response(_branch_data(branch))

    def patch(self, request, branch_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        branch = self._get_branch(branch_id)
        if not branch:
            return Response({"detail": "Sucursal no encontrada."}, status=404)

        update_fields = []

        if "name" in request.data:
            branch.name = request.data["name"].strip()
            update_fields.append("name")

        if "grace_period_days" in request.data:
            try:
                grace = int(request.data["grace_period_days"])
                if grace < 0:
                    raise ValueError
                branch.grace_period_days = grace
                update_fields.append("grace_period_days")
            except (TypeError, ValueError):
                return Response(
                    {"detail": "'grace_period_days' debe ser un entero >= 0."},
                    status=400,
                )

        if "is_active" in request.data:
            branch.is_active = bool(request.data["is_active"])
            update_fields.append("is_active")

        if update_fields:
            branch.save(update_fields=update_fields)

        return Response(_branch_data(branch))


# ─────────────────────────────────────────────────────────────────────────────
# Creación de caja dentro de una sucursal
# ─────────────────────────────────────────────────────────────────────────────

class BranchCashRegisterCreateView(APIView):
    """
    POST /api/branches/{branch_id}/cash-registers — crear caja en la sucursal

    Body:
    {
      "name": "Caja 2",
      "register_type": "BRANCH",   // BRANCH | VAULT
      "min_balance": 1000.00,
      "max_balance": 4000.00
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, branch_id):
        require_roles(request.user, {"OWNER_ADMIN"})

        try:
            branch = Branch.objects.get(id=branch_id)
        except Branch.DoesNotExist:
            return Response({"detail": "Sucursal no encontrada."}, status=404)

        if not branch.is_active:
            return Response(
                {"detail": "No se pueden crear cajas en una sucursal inactiva."},
                status=400,
            )

        name = request.data.get("name", "").strip()
        reg_type = request.data.get("register_type", "BRANCH").upper()

        if not name:
            return Response({"detail": "'name' es requerido."}, status=400)

        valid_types = {CashRegister.RegisterType.BRANCH, CashRegister.RegisterType.VAULT}
        if reg_type not in valid_types:
            return Response(
                {"detail": f"'register_type' debe ser BRANCH o VAULT. Recibido: {reg_type}"},
                status=400,
            )

        min_bal = Decimal("1000.00")
        max_bal = Decimal("4000.00")

        try:
            if "min_balance" in request.data:
                min_bal = Decimal(str(request.data["min_balance"]))
            if "max_balance" in request.data:
                max_bal = Decimal(str(request.data["max_balance"]))
        except (InvalidOperation, TypeError):
            return Response({"detail": "min_balance/max_balance deben ser números decimales."}, status=400)

        if min_bal >= max_bal:
            return Response(
                {"detail": "min_balance debe ser menor que max_balance."},
                status=400,
            )

        register = CashRegister.objects.create(
            name=name,
            register_type=reg_type,
            branch=branch,
            is_active=True,
            min_balance=min_bal,
            max_balance=max_bal,
        )

        return Response({
            "register_id":   str(register.public_id),
            "name":          register.name,
            "register_type": register.register_type,
            "branch_code":   branch.code,
            "is_active":     register.is_active,
            "min_balance":   str(register.min_balance),
            "max_balance":   str(register.max_balance),
        }, status=201)


# ─────────────────────────────────────────────────────────────────────────────
# Actualización de configuración de caja
# ─────────────────────────────────────────────────────────────────────────────

class CashRegisterSettingsView(APIView):
    """
    GET   /api/cash-registers/{register_id}/settings — ver config de la caja
    PATCH /api/cash-registers/{register_id}/settings — actualizar config

    Body PATCH (todos opcionales):
    {
      "name": "Caja Principal",
      "min_balance": 1500.00,
      "max_balance": 5000.00,
      "is_active": true
    }
    """
    permission_classes = [IsAuthenticated]

    def _get_register(self, register_id):
        try:
            return CashRegister.objects.select_related("branch").get(public_id=register_id)
        except CashRegister.DoesNotExist:
            return None

    def get(self, request, register_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        reg = self._get_register(register_id)
        if not reg:
            return Response({"detail": "Caja no encontrada."}, status=404)

        return Response({
            "register_id":   str(reg.public_id),
            "name":          reg.name,
            "register_type": reg.register_type,
            "branch_code":   reg.branch.code if reg.branch else None,
            "is_active":     reg.is_active,
            "min_balance":   str(reg.min_balance),
            "max_balance":   str(reg.max_balance),
        })

    def patch(self, request, register_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        reg = self._get_register(register_id)
        if not reg:
            return Response({"detail": "Caja no encontrada."}, status=404)

        update_fields = []

        if "name" in request.data:
            reg.name = request.data["name"].strip()
            update_fields.append("name")

        if "is_active" in request.data:
            reg.is_active = bool(request.data["is_active"])
            update_fields.append("is_active")

        min_bal = reg.min_balance
        max_bal = reg.max_balance

        try:
            if "min_balance" in request.data:
                min_bal = Decimal(str(request.data["min_balance"]))
                update_fields.append("min_balance")
            if "max_balance" in request.data:
                max_bal = Decimal(str(request.data["max_balance"]))
                update_fields.append("max_balance")
        except (InvalidOperation, TypeError):
            return Response({"detail": "min_balance/max_balance deben ser números decimales."}, status=400)

        if min_bal >= max_bal:
            return Response(
                {"detail": "min_balance debe ser menor que max_balance."},
                status=400,
            )

        reg.min_balance = min_bal
        reg.max_balance = max_bal

        if update_fields:
            reg.save(update_fields=list(set(update_fields)))

        return Response({
            "register_id":   str(reg.public_id),
            "name":          reg.name,
            "register_type": reg.register_type,
            "branch_code":   reg.branch.code if reg.branch else None,
            "is_active":     reg.is_active,
            "min_balance":   str(reg.min_balance),
            "max_balance":   str(reg.max_balance),
        })
