"""
Reporte de Aguinaldo — Frontend
=================================
GET /api/reports/hr/aguinaldo/<year>

Diseñado para que el frontend pueda renderizar directamente:
  - Encabezado legal con fechas de pago
  - Tabla de empleados con todos los conceptos
  - Resumen financiero por sucursal
  - Panel de estado (cuántos pagados, pendientes, vencidos)
  - Alertas de cumplimiento (días restantes al vencimiento del 20/dic)
  - Detalle de doble aguinaldo si existe

Query params:
  type       → REGULAR | DOBLE | ALL (default: ALL — incluye ambos tipos)
  branch     → código de sucursal para filtrar
  status     → DRAFT | APPROVED | PAID para filtrar
"""
from datetime import date
from decimal import Decimal

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models_hr import AguinaldoPeriod, Employee
from core.services.hr_calculator import (
    calculate_aguinaldo,
    AGUINALDO_PAYMENT_DEADLINE_DAY,
    AGUINALDO_PAYMENT_DEADLINE_MONTH,
)


def _days_until_deadline(year: int) -> int:
    deadline = date(year, AGUINALDO_PAYMENT_DEADLINE_MONTH, AGUINALDO_PAYMENT_DEADLINE_DAY)
    return (deadline - date.today()).days


class AguinaldoReportView(APIView):
    """
    GET /api/reports/hr/aguinaldo/<year>
    Reporte completo de aguinaldo listo para el frontend.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, year):
        require_roles(request.user, {"OWNER_ADMIN", "SUPERVISOR"})

        atype_filter  = request.query_params.get("type",   "ALL").upper()
        branch_filter = request.query_params.get("branch", None)
        status_filter = request.query_params.get("status", None)

        today    = date.today()
        deadline = date(year, AGUINALDO_PAYMENT_DEADLINE_MONTH, AGUINALDO_PAYMENT_DEADLINE_DAY)
        days_left = (deadline - today).days

        # ── Determinar si incluir REGULAR, DOBLE o ambos ──────────────────────
        type_options = (
            ["REGULAR", "DOBLE"] if atype_filter == "ALL"
            else [atype_filter]
        )

        # ── Obtener registros de la BD ────────────────────────────────────────
        qs = (
            AguinaldoPeriod.objects
            .filter(year=year, aguinaldo_type__in=type_options)
            .select_related("employee", "employee__branch")
            .order_by("aguinaldo_type", "employee__last_name_paternal")
        )
        if branch_filter:
            qs = qs.filter(employee__branch__code=branch_filter)
        if status_filter:
            qs = qs.filter(status=status_filter.upper())

        records = list(qs)

        # ── Empleados activos sin aguinaldo generado (alerta) ─────────────────
        active_employees = Employee.objects.filter(
            status__in=[Employee.Status.ACTIVE, Employee.Status.ON_VACATION]
        )
        if branch_filter:
            active_employees = active_employees.filter(branch__code=branch_filter)

        employees_with_record = {r.employee_id for r in records}
        missing_employees = [
            {"ci": e.ci, "name": e.full_name, "branch": e.branch.code}
            for e in active_employees
            if e.id not in employees_with_record
        ]

        # ── Tabla principal ───────────────────────────────────────────────────
        table_rows = []
        for a in records:
            emp = a.employee
            table_rows.append({
                "id":                    a.id,
                "aguinaldo_type":        a.aguinaldo_type,
                "aguinaldo_type_label":  "Regular" if a.aguinaldo_type == "REGULAR" else "Doble (Esfuerzo Bolivia)",
                # Empleado
                "employee_ci":           emp.ci,
                "employee_name":         emp.full_name,
                "branch":                emp.branch.code,
                "work_schedule":         emp.work_schedule,
                "work_schedule_label":   "Tiempo Completo" if emp.work_schedule == "FULL_TIME" else "Medio Tiempo",
                # Cálculo
                "hire_date":             str(a.hire_date_snapshot),
                "months_in_period":      str(a.months_in_period),
                "days_worked_in_year":   a.days_worked_in_year,
                "qualifies":             a.qualifies,
                "base_salary":           str(a.base_salary_snapshot),
                "amount":                str(a.amount),
                # Estado
                "status":                a.status,
                "status_label":          {"DRAFT": "Borrador", "APPROVED": "Aprobado", "PAID": "Pagado"}.get(a.status, a.status),
                "paid_at":               a.paid_at.isoformat() if a.paid_at else None,
                "notes":                 a.notes,
            })

        # ── Resumen financiero global ─────────────────────────────────────────
        def _sum(filter_fn) -> Decimal:
            return sum((Decimal(r["amount"]) for r in table_rows if filter_fn(r)), Decimal("0"))

        total_regular = _sum(lambda r: r["aguinaldo_type"] == "REGULAR" and r["qualifies"])
        total_doble   = _sum(lambda r: r["aguinaldo_type"] == "DOBLE"   and r["qualifies"])
        total_all     = total_regular + total_doble
        total_paid    = _sum(lambda r: r["status"] == "PAID")
        total_pending = _sum(lambda r: r["status"] in ("DRAFT", "APPROVED") and r["qualifies"])

        # ── Resumen por sucursal ──────────────────────────────────────────────
        branch_map: dict[str, dict] = {}
        for r in table_rows:
            b = r["branch"]
            if b not in branch_map:
                branch_map[b] = {
                    "branch":         b,
                    "count":          0,
                    "total_regular":  Decimal("0"),
                    "total_doble":    Decimal("0"),
                    "paid_count":     0,
                    "pending_count":  0,
                }
            branch_map[b]["count"] += 1
            if r["aguinaldo_type"] == "REGULAR":
                branch_map[b]["total_regular"] += Decimal(r["amount"])
            else:
                branch_map[b]["total_doble"] += Decimal(r["amount"])
            if r["status"] == "PAID":
                branch_map[b]["paid_count"] += 1
            else:
                branch_map[b]["pending_count"] += 1

        by_branch = [
            {
                **{k: str(v) if isinstance(v, Decimal) else v for k, v in d.items()}
            }
            for d in sorted(branch_map.values(), key=lambda x: x["branch"])
        ]

        # ── Estado de cumplimiento (semáforo) ─────────────────────────────────
        paid_count     = sum(1 for r in table_rows if r["status"] == "PAID")
        approved_count = sum(1 for r in table_rows if r["status"] == "APPROVED")
        draft_count    = sum(1 for r in table_rows if r["status"] == "DRAFT")
        qualifies_count= sum(1 for r in table_rows if r["qualifies"])

        if days_left < 0:
            deadline_status = "VENCIDO"
            deadline_color  = "RED"
        elif days_left <= 5:
            deadline_status = "URGENTE"
            deadline_color  = "ORANGE"
        elif days_left <= 15:
            deadline_status = "PROXIMO"
            deadline_color  = "YELLOW"
        else:
            deadline_status = "OK"
            deadline_color  = "GREEN"

        # ── Alertas ───────────────────────────────────────────────────────────
        alerts = []

        if days_left < 0 and total_pending > 0:
            alerts.append({
                "level":   "CRITICAL",
                "code":    "DEADLINE_OVERDUE",
                "message": (
                    f"El plazo legal de pago de aguinaldo venció el "
                    f"{deadline.strftime('%d/%m/%Y')}. "
                    f"Hay Bs.{total_pending:,.2f} pendientes de pago."
                ),
            })
        elif days_left <= 5 and total_pending > 0:
            alerts.append({
                "level":   "WARNING",
                "code":    "DEADLINE_NEAR",
                "message": (
                    f"Quedan {days_left} días para el vencimiento del aguinaldo "
                    f"({deadline.strftime('%d/%m/%Y')}). "
                    f"Pendiente: Bs.{total_pending:,.2f}."
                ),
            })

        if missing_employees:
            alerts.append({
                "level":   "WARNING",
                "code":    "EMPLOYEES_WITHOUT_AGUINALDO",
                "message": (
                    f"{len(missing_employees)} empleado(s) activo(s) no tienen "
                    f"aguinaldo generado para {year}."
                ),
                "employees": missing_employees,
            })

        if draft_count > 0:
            alerts.append({
                "level":   "INFO",
                "code":    "DRAFTS_PENDING_APPROVAL",
                "message": f"{draft_count} aguinaldo(s) en estado BORRADOR esperan aprobación.",
            })

        # ── Normativa resumida (para mostrar en el frontend) ──────────────────
        normativa = {
            "base_legal":    "DS 110 (aguinaldo regular) / DS 1802 (doble aguinaldo)",
            "formula":       "Sueldo_Base ÷ 12 × Meses_en_Periodo",
            "periodo":       "1 enero – 30 noviembre del año en curso",
            "proporcional":  "Si el empleado ingresó durante el año, se calcula desde su mes de ingreso",
            "minimo_dias":   "90 días trabajados en el año para calificar",
            "medio_tiempo":  "Aplica igual; el sueldo base ya refleja la jornada parcial",
            "pago_deadline":  f"Antes del {AGUINALDO_PAYMENT_DEADLINE_DAY} de diciembre",
            "doble_aguinaldo": "Se activa solo cuando el PIB nacional crece > 4.5% (decreto específico cada año)",
        }

        return Response({
            "report_title":       f"Planilla de Aguinaldo {year}",
            "generated_at":       timezone.now().isoformat(),
            "year":               year,
            "payment_deadline":   str(deadline),
            "days_until_deadline": days_left,
            "deadline_status":    deadline_status,
            "deadline_color":     deadline_color,

            # Resumen financiero
            "financial_summary": {
                "total_regular":      str(total_regular),
                "total_doble":        str(total_doble),
                "total_all":          str(total_all),
                "total_paid":         str(total_paid),
                "total_pending":      str(total_pending),
            },

            # Contadores de estado
            "status_summary": {
                "total_employees":  len(table_rows),
                "qualifies_count":  qualifies_count,
                "draft_count":      draft_count,
                "approved_count":   approved_count,
                "paid_count":       paid_count,
            },

            # Datos por sucursal
            "by_branch":     by_branch,

            # Tabla principal
            "records":       table_rows,

            # Empleados sin aguinaldo generado
            "missing_records": missing_employees,

            # Alertas de cumplimiento
            "alerts":        alerts,

            # Información normativa
            "normativa":     normativa,
        })
