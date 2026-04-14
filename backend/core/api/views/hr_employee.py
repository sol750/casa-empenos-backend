"""
RRHH — Empleados
=================
GET  /api/hr/employees              → lista (OWNER_ADMIN)
POST /api/hr/employees              → crear (OWNER_ADMIN)
GET  /api/hr/employees/<id>         → detalle (OWNER_ADMIN)
PATCH /api/hr/employees/<id>        → editar (OWNER_ADMIN)
POST /api/hr/employees/<id>/documents → subir archivos (OWNER_ADMIN)

El dueño puede modificar: sueldo, caja asignada, contrato, estado.
Al crear el empleado se puede pasar salary_scale[] para la escalera salarial.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models import Branch, CashRegister
from core.models_hr import Employee, SalaryScale
from core.services.hr_calculator import get_current_scale_salary

User = get_user_model()


def _serialize_employee(emp: Employee, detail: bool = False) -> dict:
    row = {
        "public_id":         str(emp.public_id),
        "user_id":           emp.user_id,
        "username":          emp.user.username,
        "full_name":         emp.full_name,
        "ci":                emp.ci,
        "complemento_ci":    emp.complemento_ci,
        "has_nua_cua":       bool(emp.nua_cua),
        "phone":             emp.phone,
        "branch":            emp.branch.code,
        "cash_register":     emp.cash_register.name if emp.cash_register else None,
        "contract_type":     emp.contract_type,
        "work_schedule":     emp.work_schedule,
        "hire_date":         str(emp.hire_date),
        "trial_end_date":    str(emp.trial_end_date) if emp.trial_end_date else None,
        "base_salary":       str(emp.base_salary),
        "status":            emp.status,
        "seniority_years":   emp.seniority_years,
        "seniority_months":  emp.seniority_months,
        "has_afp":           emp.has_afp,
        "weekly_hours":      emp.weekly_hours,
    }
    if detail:
        scale = list(
            emp.salary_scale.values("month_number", "salary", "note")
        )
        next_salary = get_current_scale_salary(emp)
        row.update({
            "nua_cua":        emp.nua_cua,
            "address":        emp.address,
            "salary_scale":   scale,
            "next_scale_salary": str(next_salary) if next_salary else None,
            "has_contract_file":   bool(emp.contract_file),
            "has_ci_scan":         bool(emp.ci_scan),
            "has_domicile_sketch": bool(emp.domicile_sketch),
            "created_at":     emp.created_at.isoformat(),
        })
    return row


class EmployeeListCreateView(APIView):
    """GET /api/hr/employees  |  POST /api/hr/employees"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        qs = (
            Employee.objects
            .select_related("user", "branch", "cash_register")
            .order_by("last_name_paternal", "first_name")
        )
        branch_code = request.query_params.get("branch")
        if branch_code:
            qs = qs.filter(branch__code=branch_code)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())

        return Response({
            "total":     qs.count(),
            "employees": [_serialize_employee(e) for e in qs],
        })

    def post(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        d = request.data

        # ── Validaciones básicas ──────────────────────────────────────────────
        required = ["user_id", "ci", "first_name", "last_name_paternal",
                    "hire_date", "base_salary", "branch_code"]
        missing = [f for f in required if not d.get(f)]
        if missing:
            return Response({"detail": "Campos obligatorios.", "missing": missing}, status=400)

        try:
            user = User.objects.get(pk=d["user_id"])
        except User.DoesNotExist:
            return Response({"detail": "Usuario no encontrado."}, status=400)

        if hasattr(user, "employee_profile"):
            return Response({"detail": "Este usuario ya tiene un perfil de empleado."}, status=400)

        if Employee.objects.filter(ci=d["ci"]).exists():
            return Response({"detail": f"Ya existe un empleado con CI {d['ci']}."}, status=400)

        try:
            branch = Branch.objects.get(code=d["branch_code"])
        except Branch.DoesNotExist:
            return Response({"detail": "Sucursal no encontrada."}, status=400)

        cash_register = None
        if d.get("cash_register_id"):
            try:
                cash_register = CashRegister.objects.get(pk=d["cash_register_id"])
            except CashRegister.DoesNotExist:
                return Response({"detail": "Caja no encontrada."}, status=400)

        # Convertir fechas: Django no coerciona strings a date en el objeto Python
        # devuelto por create() — solo lo hace al persistir en BD.
        # Si no se parsea antes, seniority_years/.month falla con AttributeError.
        from datetime import date as _date
        def _parse_date(val):
            if val is None:
                return None
            if isinstance(val, _date):
                return val
            return _date.fromisoformat(str(val))

        hire_date      = _parse_date(d["hire_date"])
        trial_end_date = _parse_date(d.get("trial_end_date"))

        with transaction.atomic():
            emp = Employee.objects.create(
                user              = user,
                branch            = branch,
                cash_register     = cash_register,
                first_name        = d["first_name"],
                last_name_paternal= d["last_name_paternal"],
                last_name_maternal= d.get("last_name_maternal", ""),
                ci                = d["ci"],
                complemento_ci    = d.get("complemento_ci", ""),
                nua_cua           = d.get("nua_cua", ""),
                phone             = d.get("phone", ""),
                address           = d.get("address", ""),
                contract_type     = d.get("contract_type", Employee.ContractType.INDEFINIDO),
                work_schedule     = d.get("work_schedule", Employee.WorkSchedule.HALF_TIME),
                hire_date         = hire_date,
                trial_end_date    = trial_end_date,
                base_salary       = Decimal(str(d["base_salary"])),
                created_by        = request.user,
            )

            # Escalera salarial opcional
            scale_items = d.get("salary_scale", [])
            for item in scale_items:
                SalaryScale.objects.create(
                    employee     = emp,
                    month_number = int(item["month_number"]),
                    salary       = Decimal(str(item["salary"])),
                    note         = item.get("note", ""),
                )

        # Recargar desde BD para asegurar que todos los campos son tipos Python correctos
        emp.refresh_from_db()
        return Response(_serialize_employee(emp, detail=True), status=201)


class EmployeeDetailView(APIView):
    """GET /api/hr/employees/<id>  |  PATCH /api/hr/employees/<id>"""
    permission_classes = [IsAuthenticated]

    def _get_emp(self, public_id):
        try:
            return Employee.objects.select_related(
                "user", "branch", "cash_register"
            ).get(public_id=public_id)
        except Employee.DoesNotExist:
            return None

    def get(self, request, employee_id):
        require_roles(request.user, {"OWNER_ADMIN", "SUPERVISOR"})
        emp = self._get_emp(employee_id)
        if not emp:
            return Response({"detail": "Empleado no encontrado."}, status=404)
        return Response(_serialize_employee(emp, detail=True))

    def patch(self, request, employee_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        emp = self._get_emp(employee_id)
        if not emp:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        from datetime import date as _date
        def _parse_date(val):
            if val is None:
                return None
            if isinstance(val, _date):
                return val
            return _date.fromisoformat(str(val))

        d = request.data
        updatable = [
            "first_name", "last_name_paternal", "last_name_maternal",
            "phone", "address", "contract_type", "work_schedule",
            "nua_cua", "complemento_ci",
        ]
        changed = []
        for field in updatable:
            if field in d:
                setattr(emp, field, d[field])
                changed.append(field)

        # Campos de fecha — parsear antes de asignar
        if "trial_end_date" in d:
            emp.trial_end_date = _parse_date(d["trial_end_date"])
            changed.append("trial_end_date")
        if "hire_date" in d:
            emp.hire_date = _parse_date(d["hire_date"])
            changed.append("hire_date")

        if "base_salary" in d:
            emp.base_salary = Decimal(str(d["base_salary"]))
            changed.append("base_salary")

        if "branch_code" in d:
            try:
                emp.branch = Branch.objects.get(code=d["branch_code"])
                changed.append("branch")
            except Branch.DoesNotExist:
                return Response({"detail": "Sucursal no encontrada."}, status=400)

        if "cash_register_id" in d:
            if d["cash_register_id"] is None:
                emp.cash_register = None
            else:
                try:
                    emp.cash_register = CashRegister.objects.get(pk=d["cash_register_id"])
                except CashRegister.DoesNotExist:
                    return Response({"detail": "Caja no encontrada."}, status=400)
            changed.append("cash_register")

        # Actualizar escalera salarial (si se envía, reemplaza completo)
        if "salary_scale" in d:
            with transaction.atomic():
                emp.save()
                emp.salary_scale.all().delete()
                for item in d["salary_scale"]:
                    SalaryScale.objects.create(
                        employee     = emp,
                        month_number = int(item["month_number"]),
                        salary       = Decimal(str(item["salary"])),
                        note         = item.get("note", ""),
                    )
        else:
            emp.save()

        return Response(_serialize_employee(emp, detail=True))


class EmployeeDocumentUploadView(APIView):
    """
    POST /api/hr/employees/<id>/documents
    Multipart: contract_file | ci_scan | domicile_sketch
    """
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request, employee_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        try:
            emp = Employee.objects.get(public_id=employee_id)
        except Employee.DoesNotExist:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        updated = []
        for field in ("contract_file", "ci_scan", "domicile_sketch"):
            if field in request.FILES:
                setattr(emp, field, request.FILES[field])
                updated.append(field)

        if not updated:
            return Response({"detail": "No se recibió ningún archivo."}, status=400)

        emp.save(update_fields=updated + ["updated_at"])
        return Response({
            "updated": updated,
            "has_contract_file":   bool(emp.contract_file),
            "has_ci_scan":         bool(emp.ci_scan),
            "has_domicile_sketch": bool(emp.domicile_sketch),
        })
