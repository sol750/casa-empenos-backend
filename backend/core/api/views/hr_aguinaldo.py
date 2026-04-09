"""
RRHH — Aguinaldo
=================
POST /api/hr/aguinaldo/generate           → Genera aguinaldos para todos (OWNER_ADMIN)
GET  /api/hr/aguinaldo/<year>             → Lista aguinaldos del año
GET  /api/hr/aguinaldo/<year>/preview     → Preview sin guardar (útil antes de diciembre)
PATCH /api/hr/aguinaldo/<id>              → Aprobar / marcar pagado
GET  /api/hr/employees/<id>/aguinaldos    → Historial de aguinaldos de un empleado

Flujo típico del dueño:
  1. Noviembre: GET preview → revisar montos antes de comprometer
  2. Diciembre 1-19: POST generate → crea DRAFTs para todos
  3. Revisar → PATCH status=APPROVED por empleado o en bloque
  4. Pagar antes del 20/12 → PATCH status=PAID
  5. Si el gobierno decreta doble aguinaldo: POST generate con type=DOBLE
"""
from decimal import Decimal

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models_hr import Employee, AguinaldoPeriod
from core.services.hr_calculator import (
    calculate_aguinaldo,
    generate_aguinaldo_for_all,
    AGUINALDO_PAYMENT_DEADLINE_DAY,
    AGUINALDO_PAYMENT_DEADLINE_MONTH,
)


def _serialize(a: AguinaldoPeriod) -> dict:
    return {
        "id":                    a.id,
        "employee_ci":           a.employee.ci,
        "employee_name":         a.employee.full_name,
        "branch":                a.employee.branch.code,
        "work_schedule":         a.employee.work_schedule,
        "year":                  a.year,
        "aguinaldo_type":        a.aguinaldo_type,
        "hire_date_snapshot":    str(a.hire_date_snapshot),
        "base_salary_snapshot":  str(a.base_salary_snapshot),
        "months_in_period":      str(a.months_in_period),
        "days_worked_in_year":   a.days_worked_in_year,
        "qualifies":             a.qualifies,
        "amount":                str(a.amount),
        "status":                a.status,
        "approved_at":           a.approved_at.isoformat() if a.approved_at else None,
        "paid_at":               a.paid_at.isoformat()     if a.paid_at     else None,
        "notes":                 a.notes,
        "created_at":            a.created_at.isoformat(),
    }


class AguinaldoGenerateView(APIView):
    """
    POST /api/hr/aguinaldo/generate
    Body: { "year": 2026, "type": "REGULAR" }   (type opcional, default REGULAR)

    Genera (o actualiza en DRAFT) los registros de aguinaldo para todos los
    empleados activos. Si ya existe un registro APPROVED o PAID, lo omite.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})

        year  = int(request.data.get("year", timezone.now().year))
        atype = request.data.get("type", "REGULAR").upper()

        if atype not in ("REGULAR", "DOBLE"):
            return Response({"detail": "type debe ser REGULAR o DOBLE."}, status=400)

        results     = generate_aguinaldo_for_all(year, atype)
        created     = []
        updated     = []
        skipped     = []

        for r in results:
            emp = r.pop("employee")
            # Si ya está APPROVED/PAID, no tocar
            existing = AguinaldoPeriod.objects.filter(
                employee=emp, year=year, aguinaldo_type=atype
            ).first()

            if existing and existing.status in (
                AguinaldoPeriod.Status.APPROVED, AguinaldoPeriod.Status.PAID
            ):
                skipped.append(emp.ci)
                continue

            payload = {
                "hire_date_snapshot":   r["hire_date_snapshot"],
                "base_salary_snapshot": r["base_salary_snapshot"],
                "months_in_period":     r["months_in_period"],
                "days_worked_in_year":  r["days_worked_in_year"],
                "qualifies":            r["qualifies"],
                "amount":               r["amount"],
                "status":               AguinaldoPeriod.Status.DRAFT,
            }

            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
                existing.save()
                updated.append(_serialize(existing))
            else:
                a = AguinaldoPeriod.objects.create(
                    employee=emp, year=year, aguinaldo_type=atype, **payload
                )
                created.append(_serialize(a))

        total_amount = sum(
            Decimal(r["amount"]) for r in (created + updated) if r["qualifies"]
        )

        return Response({
            "year":           year,
            "type":           atype,
            "payment_deadline": f"{year}-{AGUINALDO_PAYMENT_DEADLINE_MONTH:02d}-{AGUINALDO_PAYMENT_DEADLINE_DAY:02d}",
            "created":        len(created),
            "updated":        len(updated),
            "skipped":        len(skipped),
            "total_amount":   str(total_amount),
            "records":        created + updated,
        }, status=201)


class AguinaldoYearView(APIView):
    """
    GET /api/hr/aguinaldo/<year>?type=REGULAR
    Lista todos los aguinaldos del año con resumen de totales.

    GET /api/hr/aguinaldo/<year>/preview
    Preview sin crear registros (útil para revisar montos).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, year, preview=False):
        require_roles(request.user, {"OWNER_ADMIN"})
        atype = request.query_params.get("type", "REGULAR").upper()

        if preview:
            # Calcula en memoria, no toca la BD
            raw = generate_aguinaldo_for_all(year, atype)
            records = []
            for r in raw:
                emp = r.pop("employee")
                records.append({
                    "employee_ci":          emp.ci,
                    "employee_name":        emp.full_name,
                    "branch":               emp.branch.code,
                    "work_schedule":        emp.work_schedule,
                    "hire_date_snapshot":   str(r["hire_date_snapshot"]),
                    "base_salary_snapshot": str(r["base_salary_snapshot"]),
                    "months_in_period":     str(r["months_in_period"]),
                    "days_worked_in_year":  r["days_worked_in_year"],
                    "qualifies":            r["qualifies"],
                    "amount":               str(r["amount"]),
                    "legal_basis":          r["legal_basis"],
                })
            total = sum(Decimal(r["amount"]) for r in records if r["qualifies"])
            return Response({
                "year":             year,
                "type":             atype,
                "preview":          True,
                "payment_deadline": f"{year}-{AGUINALDO_PAYMENT_DEADLINE_MONTH:02d}-{AGUINALDO_PAYMENT_DEADLINE_DAY:02d}",
                "total_employees":  len(records),
                "qualifies_count":  sum(1 for r in records if r["qualifies"]),
                "total_amount":     str(total),
                "records":          records,
            })

        # Datos reales de la BD
        qs = (
            AguinaldoPeriod.objects
            .filter(year=year, aguinaldo_type=atype)
            .select_related("employee", "employee__branch")
            .order_by("employee__last_name_paternal")
        )
        records   = [_serialize(a) for a in qs]
        total_all = sum(Decimal(r["amount"]) for r in records)
        total_paid= sum(Decimal(r["amount"]) for r in records if r["status"] == "PAID")
        total_pending = total_all - total_paid

        return Response({
            "year":             year,
            "type":             atype,
            "payment_deadline": f"{year}-{AGUINALDO_PAYMENT_DEADLINE_MONTH:02d}-{AGUINALDO_PAYMENT_DEADLINE_DAY:02d}",
            "total_employees":  len(records),
            "total_amount":     str(total_all),
            "total_paid":       str(total_paid),
            "total_pending":    str(total_pending),
            "status_summary": {
                "DRAFT":    sum(1 for r in records if r["status"] == "DRAFT"),
                "APPROVED": sum(1 for r in records if r["status"] == "APPROVED"),
                "PAID":     sum(1 for r in records if r["status"] == "PAID"),
            },
            "records": records,
        })


class AguinaldoPreviewView(AguinaldoYearView):
    """GET /api/hr/aguinaldo/<year>/preview"""
    def get(self, request, year):
        return super().get(request, year, preview=True)


class AguinaldoDetailView(APIView):
    """
    GET   /api/hr/aguinaldo/detail/<id>
    PATCH /api/hr/aguinaldo/detail/<id>   → aprobar o marcar pagado

    Flujo de estados:  DRAFT → APPROVED → PAID
    Solo se puede avanzar, nunca retroceder.
    """
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        try:
            return AguinaldoPeriod.objects.select_related(
                "employee", "employee__branch"
            ).get(pk=pk)
        except AguinaldoPeriod.DoesNotExist:
            return None

    def get(self, request, aguinaldo_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        a = self._get(aguinaldo_id)
        if not a:
            return Response({"detail": "Aguinaldo no encontrado."}, status=404)
        return Response(_serialize(a))

    def patch(self, request, aguinaldo_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        a = self._get(aguinaldo_id)
        if not a:
            return Response({"detail": "Aguinaldo no encontrado."}, status=404)

        if a.status == AguinaldoPeriod.Status.PAID:
            return Response({"detail": "Este aguinaldo ya fue marcado como pagado."}, status=400)

        new_status = request.data.get("status", "").upper()
        now = timezone.now()

        if new_status == AguinaldoPeriod.Status.APPROVED and a.status == AguinaldoPeriod.Status.DRAFT:
            a.status      = AguinaldoPeriod.Status.APPROVED
            a.approved_by = request.user
            a.approved_at = now

        elif new_status == AguinaldoPeriod.Status.PAID and a.status == AguinaldoPeriod.Status.APPROVED:
            a.status  = AguinaldoPeriod.Status.PAID
            a.paid_at = now

        # Ajuste manual del monto (solo en DRAFT)
        if "amount" in request.data and a.status == AguinaldoPeriod.Status.DRAFT:
            a.amount = Decimal(str(request.data["amount"]))

        if "notes" in request.data:
            a.notes = request.data["notes"]

        a.save()
        return Response(_serialize(a))


class EmployeeAguinaldoHistoryView(APIView):
    """GET /api/hr/employees/<id>/aguinaldos"""
    permission_classes = [IsAuthenticated]

    def get(self, request, employee_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        try:
            emp = Employee.objects.get(public_id=employee_id)
        except Employee.DoesNotExist:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        aguinaldos = emp.aguinaldos.all()
        total_received = sum(
            a.amount for a in aguinaldos if a.status == AguinaldoPeriod.Status.PAID
        )
        return Response({
            "employee":       emp.full_name,
            "employee_ci":    emp.ci,
            "total_received": str(total_received),
            "aguinaldos":     [_serialize(a) for a in aguinaldos],
        })
