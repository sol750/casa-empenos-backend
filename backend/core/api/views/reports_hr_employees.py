"""
Reporte de Directorio de Empleados — Frontend
===============================================
GET /api/reports/hr/employees

Retorna el estado completo del personal para el panel del dueño:
  - Plantilla activa con antigüedad, salario actual y caja asignada
  - Vacaciones pendientes por empleado
  - Próximas escalas salariales
  - Empleados en período de prueba
  - Resumen por sucursal y tipo de contrato

Query params:
  branch  → filtrar por sucursal
  status  → ACTIVE | ON_VACATION | SUSPENDED | TERMINATED (default: ACTIVE)
"""
from datetime import date
from decimal import Decimal

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models_hr import Employee, VacationPeriod, HRConfig
from core.services.hr_calculator import get_current_scale_salary, vacation_days_for_years


def _employee_row(emp: Employee, today: date, smn: Decimal) -> dict:
    current_salary = get_current_scale_salary(emp) or emp.base_salary

    # Próxima escala (mes siguiente si existe)
    next_scale = emp.salary_scale.filter(
        month_number=emp.seniority_months + 1
    ).first()

    # Vacaciones disponibles no gozadas
    vacation_pending = (
        VacationPeriod.objects
        .filter(employee=emp, status__in=("AVAILABLE", "SCHEDULED"))
        .aggregate(days=__import__("django.db.models", fromlist=["Sum"]).Sum("days_available"))
    )["days"] or 0

    vacation_taken = (
        VacationPeriod.objects
        .filter(employee=emp)
        .aggregate(taken=__import__("django.db.models", fromlist=["Sum"]).Sum("days_taken"))
    )["taken"] or 0

    # Período de prueba
    in_trial = (
        emp.trial_end_date is not None and emp.trial_end_date >= today
    )

    return {
        "employee_id":       str(emp.public_id),
        "ci":                emp.ci,
        "full_name":         emp.full_name,
        "branch":            emp.branch.code,
        "cash_register":     emp.cash_register.name if emp.cash_register else None,
        "cash_register_id":  str(emp.cash_register.public_id) if emp.cash_register else None,
        "contract_type":     emp.contract_type,
        "work_schedule":     emp.work_schedule,
        "hire_date":         str(emp.hire_date),
        "seniority_years":   emp.seniority_years,
        "seniority_months":  emp.seniority_months,
        "status":            emp.status,
        "in_trial":          in_trial,
        "trial_end_date":    str(emp.trial_end_date) if emp.trial_end_date else None,
        # Salario
        "base_salary":       str(emp.base_salary),
        "current_salary":    str(current_salary),
        "smn_coverage_pct":  round(float(current_salary / smn * 100), 1),
        # Próxima escala
        "next_scale_month":  next_scale.month_number if next_scale else None,
        "next_scale_salary": str(next_scale.salary) if next_scale else None,
        # AFP
        "has_afp":           emp.has_afp,
        "nua_cua":           emp.nua_cua if emp.has_afp else None,
        # Vacaciones
        "vacation_days_right":   vacation_days_for_years(emp.seniority_years),
        "vacation_days_pending": vacation_pending,
        "vacation_days_taken":   vacation_taken,
    }


class EmployeeDirectoryReportView(APIView):
    """GET /api/reports/hr/employees"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})

        config = HRConfig.get()
        today  = date.today()

        status_filter = request.query_params.get("status", "ACTIVE").upper()
        branch_filter = request.query_params.get("branch")

        qs = (
            Employee.objects
            .select_related("user", "branch", "cash_register")
            .prefetch_related("salary_scale")
            .filter(status=status_filter)
            .order_by("branch__code", "last_name_paternal", "first_name")
        )
        if branch_filter:
            qs = qs.filter(branch__code=branch_filter.upper())

        records = [_employee_row(e, today, config.smn) for e in qs]

        # ── Resumen por sucursal ──────────────────────────────────────────
        branches: dict = {}
        for r in records:
            b = r["branch"]
            if b not in branches:
                branches[b] = {
                    "branch": b, "total": 0,
                    "full_time": 0, "half_time": 0,
                    "in_trial": 0,
                    "total_salary_cost": Decimal("0"),
                }
            branches[b]["total"]             += 1
            branches[b]["total_salary_cost"] += Decimal(r["current_salary"])
            if r["work_schedule"] == "FULL_TIME":
                branches[b]["full_time"] += 1
            else:
                branches[b]["half_time"] += 1
            if r["in_trial"]:
                branches[b]["in_trial"] += 1

        by_branch = [
            {**v, "total_salary_cost": str(v["total_salary_cost"])}
            for v in branches.values()
        ]

        # ── Alertas ───────────────────────────────────────────────────────
        alerts = []

        in_trial = [r for r in records if r["in_trial"]]
        if in_trial:
            alerts.append({
                "type":    "IN_TRIAL",
                "message": f"{len(in_trial)} empleado(s) en período de prueba.",
                "employees": [{"ci": r["ci"], "name": r["full_name"],
                               "trial_end": r["trial_end_date"]} for r in in_trial],
            })

        without_register = [r for r in records if not r["cash_register"]]
        if without_register:
            alerts.append({
                "type":    "NO_CASH_REGISTER",
                "message": f"{len(without_register)} cajero(s) sin caja asignada.",
                "employees": [{"ci": r["ci"], "name": r["full_name"],
                               "branch": r["branch"]} for r in without_register],
            })

        with_vacation = [r for r in records if r["vacation_days_pending"] > 0]
        if with_vacation:
            alerts.append({
                "type":    "PENDING_VACATION",
                "message": f"{len(with_vacation)} empleado(s) con vacaciones pendientes de tomar.",
                "employees": [{"ci": r["ci"], "name": r["full_name"],
                               "days": r["vacation_days_pending"]} for r in with_vacation],
            })

        total_payroll_cost = sum(Decimal(r["current_salary"]) for r in records)

        return Response({
            "report_title":   f"Directorio de Empleados — {today.strftime('%d/%m/%Y')}",
            "generated_at":   timezone.now().isoformat(),
            "smn_vigente":    str(config.smn),
            "filter_status":  status_filter,
            "summary": {
                "total_employees":    len(records),
                "full_time":          sum(1 for r in records if r["work_schedule"] == "FULL_TIME"),
                "half_time":          sum(1 for r in records if r["work_schedule"] == "HALF_TIME"),
                "with_afp":           sum(1 for r in records if r["has_afp"]),
                "in_trial":           sum(1 for r in records if r["in_trial"]),
                "total_payroll_cost": str(total_payroll_cost),
            },
            "by_branch":      by_branch,
            "records":        records,
            "alerts":         alerts,
        })
