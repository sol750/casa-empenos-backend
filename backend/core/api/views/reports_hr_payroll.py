"""
Reporte de Planilla Mensual — Frontend
=======================================
GET /api/reports/hr/payroll/<year>/<month>

Diseñado para renderizar directamente:
  - Encabezado legal (empresa, período, SMN vigente)
  - Tabla de empleados con todos los conceptos salariales
  - Resumen financiero (bruto total, AFP total, neto total, por sucursal)
  - Estado de aprobación: cuántos DRAFT / APPROVED / PAID
  - Alertas: empleados sin planilla generada, planillas sin aprobar

Query params:
  branch  → filtrar por sucursal
  status  → DRAFT | APPROVED | PAID
"""
from decimal import Decimal

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models_hr import SalaryPeriod, Employee, HRConfig


def _row(p: SalaryPeriod) -> dict:
    return {
        "period_id":               p.id,
        "employee_ci":             p.employee.ci,
        "employee_name":           p.employee.full_name,
        "branch":                  p.employee.branch.code,
        "work_schedule":           p.employee.work_schedule,
        "contract_type":           p.employee.contract_type,
        # Salario
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
        # Bonos / descuentos manuales
        "performance_bonus":       str(p.performance_bonus),
        "performance_bonus_note":  p.performance_bonus_note,
        "cash_shortage_deduction": str(p.cash_shortage_deduction),
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
    }


class PayrollReportView(APIView):
    """GET /api/reports/hr/payroll/<year>/<month>"""
    permission_classes = [IsAuthenticated]

    def get(self, request, year: int, month: int):
        require_roles(request.user, {"OWNER_ADMIN"})

        config = HRConfig.get()
        qs = (
            SalaryPeriod.objects
            .select_related("employee__branch", "employee__user")
            .filter(year=year, month=month)
            .order_by("employee__branch__code", "employee__last_name_paternal")
        )

        branch_filter = request.query_params.get("branch")
        if branch_filter:
            qs = qs.filter(employee__branch__code=branch_filter.upper())

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())

        records = [_row(p) for p in qs]

        # ── Totales financieros ───────────────────────────────────────────
        total_gross      = sum(Decimal(r["total_gross"])      for r in records)
        total_net        = sum(Decimal(r["net_salary"])        for r in records)
        total_afp        = sum(Decimal(r["afp_deduction_amount"]) for r in records)
        total_bonuses    = sum(Decimal(r["performance_bonus"]) for r in records)
        total_deductions = sum(Decimal(r["total_deductions"])  for r in records)

        # ── Por sucursal ──────────────────────────────────────────────────
        branches: dict = {}
        for r in records:
            b = r["branch"]
            if b not in branches:
                branches[b] = {"branch": b, "employees": 0,
                               "total_gross": Decimal("0"), "total_net": Decimal("0")}
            branches[b]["employees"]   += 1
            branches[b]["total_gross"] += Decimal(r["total_gross"])
            branches[b]["total_net"]   += Decimal(r["net_salary"])

        by_branch = [
            {**v, "total_gross": str(v["total_gross"]), "total_net": str(v["total_net"])}
            for v in branches.values()
        ]

        # ── Estado de aprobación ──────────────────────────────────────────
        status_summary = {
            "DRAFT":    sum(1 for r in records if r["status"] == "DRAFT"),
            "APPROVED": sum(1 for r in records if r["status"] == "APPROVED"),
            "PAID":     sum(1 for r in records if r["status"] == "PAID"),
        }

        # ── Empleados ACTIVOS sin planilla en este mes ────────────────────
        period_employee_ids = qs.values_list("employee_id", flat=True)
        missing = list(
            Employee.objects
            .filter(status=Employee.Status.ACTIVE)
            .exclude(id__in=period_employee_ids)
            .select_related("branch")
            .values("ci", "first_name", "last_name_paternal", "branch__code")
        )
        alerts = []
        if missing:
            alerts.append({
                "type":    "MISSING_PAYROLL",
                "message": f"{len(missing)} empleado(s) activo(s) sin planilla en {year}-{month:02d}.",
                "employees": [
                    {"ci": e["ci"],
                     "name": f"{e['first_name']} {e['last_name_paternal']}",
                     "branch": e["branch__code"]}
                    for e in missing
                ],
            })
        if status_summary["DRAFT"] > 0:
            alerts.append({
                "type":    "PENDING_APPROVAL",
                "message": f"{status_summary['DRAFT']} planilla(s) en borrador pendientes de aprobación.",
            })

        MONTHS = ["", "Enero","Febrero","Marzo","Abril","Mayo","Junio",
                  "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]

        return Response({
            "report_title":   f"Planilla de Sueldos — {MONTHS[month]} {year}",
            "period":         {"year": year, "month": month, "month_name": MONTHS[month]},
            "generated_at":   timezone.now().isoformat(),
            "smn_vigente":    str(config.smn),
            "afp_rate_pct":   str(config.afp_rate_pct),
            "financial_summary": {
                "total_employees":   len(records),
                "total_gross":       str(total_gross),
                "total_afp":         str(total_afp),
                "total_bonuses":     str(total_bonuses),
                "total_deductions":  str(total_deductions),
                "total_net":         str(total_net),
            },
            "status_summary":  status_summary,
            "by_branch":       by_branch,
            "records":         records,
            "alerts":          alerts,
            "missing_payroll": missing,
        })
