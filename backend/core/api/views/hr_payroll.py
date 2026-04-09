"""
RRHH — Planilla Mensual
========================
POST /api/hr/payroll/generate          → Genera pre-planilla para 1 empleado (OWNER_ADMIN)
GET  /api/hr/payroll                   → Lista planillas (OWNER_ADMIN)
GET  /api/hr/payroll/<year>/<month>    → Pre-planilla de todo el personal para ese mes
PATCH /api/hr/payroll/<id>             → Ajustes manuales + aprobar/marcar pagada
POST /api/hr/config                    → Actualizar SMN y parámetros legales
GET  /api/hr/config                    → Ver configuración actual
"""
from decimal import Decimal

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models_hr import Employee, SalaryPeriod, HRConfig
from core.services.hr_calculator import generate_payroll


def _serialize_period(p: SalaryPeriod) -> dict:
    return {
        "id":                      p.id,
        "employee_ci":             p.employee.ci,
        "employee_name":           p.employee.full_name,
        "year":                    p.year,
        "month":                   p.month,
        "base_salary":             str(p.base_salary),
        "days_worked":             p.days_worked,
        # Extras
        "overtime_hours":          str(p.overtime_hours),
        "overtime_amount":         str(p.overtime_amount),
        "night_surcharge_hours":   str(p.night_surcharge_hours),
        "night_surcharge_amount":  str(p.night_surcharge_amount),
        # Antigüedad
        "seniority_years":         p.seniority_years,
        "seniority_pct":           str(p.seniority_pct),
        "seniority_bonus_amount":  str(p.seniority_bonus_amount),
        # Bonos y descuentos
        "performance_bonus":       str(p.performance_bonus),
        "performance_bonus_note":  p.performance_bonus_note,
        "cash_shortage_deduction": str(p.cash_shortage_deduction),
        "cash_shortage_note":      p.cash_shortage_note,
        "other_deductions":        str(p.other_deductions),
        # AFP
        "afp_deduction_pct":       str(p.afp_deduction_pct),
        "afp_deduction_amount":    str(p.afp_deduction_amount),
        # Totales
        "total_gross":             str(p.total_gross),
        "total_deductions":        str(p.total_deductions),
        "net_salary":              str(p.net_salary),
        # Estado
        "status":                  p.status,
        "approved_at":             p.approved_at.isoformat() if p.approved_at else None,
        "paid_at":                 p.paid_at.isoformat() if p.paid_at else None,
        "notes":                   p.notes,
    }


def _recalculate_totals(p: SalaryPeriod) -> SalaryPeriod:
    """Recalcula total_gross, total_deductions y net_salary."""
    p.total_gross = (
        p.base_salary
        + p.overtime_amount
        + p.night_surcharge_amount
        + p.seniority_bonus_amount
        + p.performance_bonus
    ).quantize(Decimal("0.01"))
    p.total_deductions = (
        p.afp_deduction_amount
        + p.cash_shortage_deduction
        + p.other_deductions
    ).quantize(Decimal("0.01"))
    p.net_salary = (p.total_gross - p.total_deductions).quantize(Decimal("0.01"))
    return p


class HRConfigView(APIView):
    """GET/POST /api/hr/config"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        cfg = HRConfig.get()
        return Response({
            "smn":                        str(cfg.smn),
            "afp_rate_pct":               str(cfg.afp_rate_pct),
            "night_surcharge_start_hour": cfg.night_surcharge_start_hour,
            "night_surcharge_pct":        str(cfg.night_surcharge_pct),
            "updated_at":                 cfg.updated_at.isoformat(),
        })

    def post(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        cfg = HRConfig.get()
        d   = request.data
        if "smn" in d:
            cfg.smn = Decimal(str(d["smn"]))
        if "afp_rate_pct" in d:
            cfg.afp_rate_pct = Decimal(str(d["afp_rate_pct"]))
        if "night_surcharge_start_hour" in d:
            cfg.night_surcharge_start_hour = int(d["night_surcharge_start_hour"])
        if "night_surcharge_pct" in d:
            cfg.night_surcharge_pct = Decimal(str(d["night_surcharge_pct"]))
        cfg.updated_by = request.user
        cfg.save()
        return Response({"detail": "Configuración RRHH actualizada.", "smn": str(cfg.smn)})


class PayrollGenerateView(APIView):
    """POST /api/hr/payroll/generate"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        d = request.data

        ci   = d.get("employee_ci")
        year = d.get("year")
        month= d.get("month")

        if not all([ci, year, month]):
            return Response({"detail": "employee_ci, year y month son obligatorios."}, status=400)

        try:
            emp = Employee.objects.get(ci=ci)
        except Employee.DoesNotExist:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        if SalaryPeriod.objects.filter(employee=emp, year=year, month=month).exists():
            return Response({"detail": f"Ya existe planilla {year}-{month:02d} para {ci}. Use PATCH para ajustar."}, status=400)

        cfg = HRConfig.get()
        data = generate_payroll(emp, int(year), int(month), cfg.smn, cfg.afp_rate_pct)
        data.pop("employee")

        period = SalaryPeriod.objects.create(employee=emp, **data)
        return Response(_serialize_period(period), status=201)


class PayrollListView(APIView):
    """GET /api/hr/payroll?year=Y&month=M&status=DRAFT"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        qs = SalaryPeriod.objects.select_related("employee").order_by("-year", "-month", "employee__last_name_paternal")

        year  = request.query_params.get("year")
        month = request.query_params.get("month")
        st    = request.query_params.get("status")
        if year:
            qs = qs.filter(year=int(year))
        if month:
            qs = qs.filter(month=int(month))
        if st:
            qs = qs.filter(status=st.upper())

        return Response({
            "total":    qs.count(),
            "periods":  [_serialize_period(p) for p in qs[:100]],
        })


class PayrollMonthView(APIView):
    """
    GET  /api/hr/payroll/<year>/<month>  → planillas del mes completo
    POST /api/hr/payroll/<year>/<month>  → genera planillas de TODOS los empleados activos
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, year, month):
        require_roles(request.user, {"OWNER_ADMIN"})
        periods = (
            SalaryPeriod.objects
            .filter(year=year, month=month)
            .select_related("employee")
            .order_by("employee__last_name_paternal")
        )
        total_net = sum(p.net_salary for p in periods)
        return Response({
            "year":      year,
            "month":     month,
            "count":     periods.count(),
            "total_net": str(total_net),
            "periods":   [_serialize_period(p) for p in periods],
        })

    def post(self, request, year, month):
        """Genera planillas en bloque para todos los empleados activos."""
        require_roles(request.user, {"OWNER_ADMIN"})
        cfg = HRConfig.get()
        employees = Employee.objects.filter(status=Employee.Status.ACTIVE)
        created, skipped = [], []

        for emp in employees:
            if SalaryPeriod.objects.filter(employee=emp, year=year, month=month).exists():
                skipped.append(emp.ci)
                continue
            data = generate_payroll(emp, year, month, cfg.smn, cfg.afp_rate_pct)
            data.pop("employee")
            SalaryPeriod.objects.create(employee=emp, **data)
            created.append(emp.ci)

        return Response({
            "year":    year,
            "month":   month,
            "created": len(created),
            "skipped": len(skipped),
            "created_for": created,
            "skipped_for": skipped,
        })


class PayrollDetailView(APIView):
    """
    GET   /api/hr/payroll/<id>  → detalle
    PATCH /api/hr/payroll/<id>  → ajustes manuales + cambio de estado
    """
    permission_classes = [IsAuthenticated]

    def _get(self, period_id):
        try:
            return SalaryPeriod.objects.select_related("employee").get(pk=period_id)
        except SalaryPeriod.DoesNotExist:
            return None

    def get(self, request, period_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        p = self._get(period_id)
        if not p:
            return Response({"detail": "Planilla no encontrada."}, status=404)
        return Response(_serialize_period(p))

    def patch(self, request, period_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        p = self._get(period_id)
        if not p:
            return Response({"detail": "Planilla no encontrada."}, status=404)

        if p.status == SalaryPeriod.Status.PAID:
            return Response({"detail": "No se puede modificar una planilla ya pagada."}, status=400)

        d = request.data

        # Ajustes manuales del dueño
        if "performance_bonus" in d:
            p.performance_bonus = Decimal(str(d["performance_bonus"]))
        if "performance_bonus_note" in d:
            p.performance_bonus_note = d["performance_bonus_note"]
        if "cash_shortage_deduction" in d:
            p.cash_shortage_deduction = Decimal(str(d["cash_shortage_deduction"]))
        if "cash_shortage_note" in d:
            p.cash_shortage_note = d["cash_shortage_note"]
        if "other_deductions" in d:
            p.other_deductions = Decimal(str(d["other_deductions"]))
        if "other_deductions_note" in d:
            p.other_deductions_note = d["other_deductions_note"]
        if "notes" in d:
            p.notes = d["notes"]

        # Cambio de estado
        new_status = d.get("status", "").upper()
        if new_status == SalaryPeriod.Status.APPROVED and p.status == SalaryPeriod.Status.DRAFT:
            p.status      = SalaryPeriod.Status.APPROVED
            p.approved_by = request.user
            p.approved_at = timezone.now()
        elif new_status == SalaryPeriod.Status.PAID and p.status == SalaryPeriod.Status.APPROVED:
            p.status  = SalaryPeriod.Status.PAID
            p.paid_at = timezone.now()

        p = _recalculate_totals(p)
        p.save()
        return Response(_serialize_period(p))
