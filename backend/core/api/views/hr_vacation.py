"""
RRHH — Vacaciones
==================
GET  /api/hr/employees/<id>/vacations    → Períodos vacacionales del empleado
POST /api/hr/employees/<id>/vacations    → Designar fechas de vacaciones (OWNER_ADMIN)
PATCH /api/hr/vacations/<id>             → Aprobar / marcar como gozadas
"""
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models_hr import Employee, VacationPeriod
from core.services.hr_calculator import check_vacation_accrual, vacation_days_for_years


def _serialize_vacation(v: VacationPeriod) -> dict:
    return {
        "id":              v.id,
        "employee_ci":     v.employee.ci,
        "employee_name":   v.employee.full_name,
        "accrual_year":    v.accrual_year,
        "calendar_year":   v.calendar_year,
        "days_available":  v.days_available,
        "days_taken":      v.days_taken,
        "days_remaining":  v.days_remaining,
        "start_date":      str(v.start_date)  if v.start_date  else None,
        "end_date":        str(v.end_date)    if v.end_date    else None,
        "status":          v.status,
        "approved_at":     v.approved_at.isoformat() if v.approved_at else None,
        "notes":           v.notes,
    }


class EmployeeVacationView(APIView):
    """
    GET  /api/hr/employees/<id>/vacations  → historial de vacaciones
    POST /api/hr/employees/<id>/vacations  → designar fechas
    """
    permission_classes = [IsAuthenticated]

    def _get_emp(self, employee_id):
        try:
            return Employee.objects.get(public_id=employee_id)
        except Employee.DoesNotExist:
            return None

    def get(self, request, employee_id):
        require_roles(request.user, {"OWNER_ADMIN", "SUPERVISOR"})
        emp = self._get_emp(employee_id)
        if not emp:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        # Verificar si acumuló nuevo período
        check_vacation_accrual(emp)

        vacations = list(emp.vacations.all())
        total_available = sum(v.days_remaining for v in vacations if v.status in (
            VacationPeriod.Status.AVAILABLE, VacationPeriod.Status.SCHEDULED
        ))

        return Response({
            "employee":           emp.full_name,
            "seniority_years":    emp.seniority_years,
            "days_per_year":      vacation_days_for_years(emp.seniority_years),
            "total_days_available": total_available,
            "vacations":          [_serialize_vacation(v) for v in vacations],
        })

    def post(self, request, employee_id):
        """Designar fechas de vacaciones para un período."""
        require_roles(request.user, {"OWNER_ADMIN"})
        emp = self._get_emp(employee_id)
        if not emp:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        d = request.data
        accrual_year = d.get("accrual_year")
        start_date   = d.get("start_date")
        end_date     = d.get("end_date")

        if not all([accrual_year, start_date, end_date]):
            return Response({"detail": "accrual_year, start_date y end_date son obligatorios."}, status=400)

        try:
            vac = emp.vacations.get(accrual_year=int(accrual_year))
        except VacationPeriod.DoesNotExist:
            return Response({"detail": f"No existe período vacacional para año laboral {accrual_year}."}, status=404)

        if vac.status not in (VacationPeriod.Status.AVAILABLE, VacationPeriod.Status.SCHEDULED):
            return Response({"detail": f"El período está en estado {vac.status} y no se puede designar."}, status=400)

        vac.start_date  = start_date
        vac.end_date    = end_date
        vac.status      = VacationPeriod.Status.SCHEDULED
        vac.approved_by = request.user
        vac.approved_at = timezone.now()
        vac.notes       = d.get("notes", vac.notes)
        vac.save()

        # Cambiar estado del empleado a ON_VACATION
        emp.status = Employee.Status.ON_VACATION
        emp.save(update_fields=["status", "updated_at"])

        return Response({
            "detail":   "Vacaciones designadas.",
            "vacation": _serialize_vacation(vac),
        })


class VacationDetailView(APIView):
    """PATCH /api/hr/vacations/<id>"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, vacation_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        try:
            vac = VacationPeriod.objects.select_related("employee").get(pk=vacation_id)
        except VacationPeriod.DoesNotExist:
            return Response({"detail": "Período vacacional no encontrado."}, status=404)

        d = request.data
        new_status = d.get("status", "").upper()

        if new_status == VacationPeriod.Status.TAKEN:
            vac.status     = VacationPeriod.Status.TAKEN
            vac.days_taken = vac.days_available
            # Reactivar al empleado
            emp = vac.employee
            emp.status = Employee.Status.ACTIVE
            emp.save(update_fields=["status", "updated_at"])

        if "notes" in d:
            vac.notes = d["notes"]

        vac.save()
        return Response({"detail": "Período vacacional actualizado.", "vacation": _serialize_vacation(vac)})
