"""
Reporte de Asistencia Mensual — Frontend
=========================================
GET /api/reports/hr/attendance/<year>/<month>

Diseñado para renderizar directamente:
  - Tabla por empleado: días trabajados, horas regulares, extras, nocturnas
  - Resumen por sucursal
  - Empleados con asistencia incompleta (clock-in sin clock-out)
  - Días sin marcar por empleado activo

Query params:
  branch      → filtrar por sucursal
  employee_ci → filtrar un empleado específico
"""
from datetime import date, timedelta
from decimal import Decimal
import calendar

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models_hr import AttendanceRecord, Employee


class AttendanceReportView(APIView):
    """GET /api/reports/hr/attendance/<year>/<month>"""
    permission_classes = [IsAuthenticated]

    def get(self, request, year: int, month: int):
        require_roles(request.user, {"OWNER_ADMIN", "SUPERVISOR"})

        qs = (
            AttendanceRecord.objects
            .select_related("employee__branch", "employee__user")
            .filter(date__year=year, date__month=month)
            .order_by("employee__last_name_paternal", "date")
        )

        branch_filter = request.query_params.get("branch")
        if branch_filter:
            qs = qs.filter(employee__branch__code=branch_filter.upper())

        ci_filter = request.query_params.get("employee_ci")
        if ci_filter:
            qs = qs.filter(employee__ci=ci_filter.upper())

        # ── Agrupar registros por empleado ────────────────────────────────
        employees_data: dict = {}
        incomplete_records = []

        for rec in qs:
            eid = rec.employee.ci
            if eid not in employees_data:
                employees_data[eid] = {
                    "employee_ci":     rec.employee.ci,
                    "employee_name":   rec.employee.full_name,
                    "branch":          rec.employee.branch.code,
                    "work_schedule":   rec.employee.work_schedule,
                    "days_recorded":   0,
                    "regular_hours":   Decimal("0"),
                    "overtime_hours":  Decimal("0"),
                    "night_hours":     Decimal("0"),
                    "daily_records":   [],
                }
            e = employees_data[eid]
            e["days_recorded"] += 1
            e["regular_hours"]  += rec.regular_hours
            e["overtime_hours"] += rec.overtime_hours
            e["night_hours"]    += rec.night_hours
            e["daily_records"].append({
                "date":           str(rec.date),
                "clock_in":       rec.clock_in.isoformat(),
                "clock_out":      rec.clock_out.isoformat() if rec.clock_out else None,
                "regular_hours":  str(rec.regular_hours),
                "overtime_hours": str(rec.overtime_hours),
                "night_hours":    str(rec.night_hours),
                "complete":       rec.clock_out is not None,
            })
            if rec.clock_out is None:
                incomplete_records.append({
                    "employee_ci":   rec.employee.ci,
                    "employee_name": rec.employee.full_name,
                    "date":          str(rec.date),
                    "clock_in":      rec.clock_in.isoformat(),
                })

        # ── Calcular días hábiles del mes ─────────────────────────────────
        _, days_in_month = calendar.monthrange(year, month)
        business_days = sum(
            1 for d in range(1, days_in_month + 1)
            if date(year, month, d).weekday() < 5
        )

        # ── Empleados activos sin ningún registro este mes ────────────────
        recorded_cis = set(employees_data.keys())
        active_employees_qs = Employee.objects.filter(status=Employee.Status.ACTIVE).select_related("branch")
        if branch_filter:
            active_employees_qs = active_employees_qs.filter(branch__code=branch_filter.upper())

        absent_employees = [
            {
                "employee_ci":   e.ci,
                "employee_name": e.full_name,
                "branch":        e.branch.code,
            }
            for e in active_employees_qs
            if e.ci not in recorded_cis
        ]

        # ── Serializar totales por empleado ───────────────────────────────
        records_out = []
        for e in employees_data.values():
            records_out.append({
                **e,
                "regular_hours":  str(e["regular_hours"]),
                "overtime_hours": str(e["overtime_hours"]),
                "night_hours":    str(e["night_hours"]),
                "attendance_pct": round(e["days_recorded"] / business_days * 100, 1) if business_days else 0,
            })

        # ── Resumen por sucursal ──────────────────────────────────────────
        branches: dict = {}
        for r in records_out:
            b = r["branch"]
            if b not in branches:
                branches[b] = {"branch": b, "employees": 0,
                               "total_regular_hours": Decimal("0"),
                               "total_overtime_hours": Decimal("0")}
            branches[b]["employees"]            += 1
            branches[b]["total_regular_hours"]  += Decimal(r["regular_hours"])
            branches[b]["total_overtime_hours"] += Decimal(r["overtime_hours"])

        by_branch = [
            {**v,
             "total_regular_hours":  str(v["total_regular_hours"]),
             "total_overtime_hours": str(v["total_overtime_hours"])}
            for v in branches.values()
        ]

        # ── Alertas ───────────────────────────────────────────────────────
        alerts = []
        if incomplete_records:
            alerts.append({
                "type":    "INCOMPLETE_RECORDS",
                "message": f"{len(incomplete_records)} registro(s) sin clock-out.",
                "records": incomplete_records,
            })
        if absent_employees:
            alerts.append({
                "type":    "NO_ATTENDANCE",
                "message": f"{len(absent_employees)} empleado(s) activo(s) sin asistencia registrada este mes.",
                "employees": absent_employees,
            })

        MONTHS = ["", "Enero","Febrero","Marzo","Abril","Mayo","Junio",
                  "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]

        return Response({
            "report_title":    f"Asistencia — {MONTHS[month]} {year}",
            "period":          {"year": year, "month": month, "month_name": MONTHS[month]},
            "generated_at":    timezone.now().isoformat(),
            "business_days":   business_days,
            "summary": {
                "employees_with_records": len(records_out),
                "employees_absent":       len(absent_employees),
                "incomplete_records":     len(incomplete_records),
                "total_regular_hours":    str(sum(Decimal(r["regular_hours"])  for r in records_out)),
                "total_overtime_hours":   str(sum(Decimal(r["overtime_hours"]) for r in records_out)),
                "total_night_hours":      str(sum(Decimal(r["night_hours"])    for r in records_out)),
            },
            "by_branch":       by_branch,
            "records":         records_out,
            "absent_employees": absent_employees,
            "alerts":          alerts,
        })
