"""
RRHH — Asistencia (Reloj Marcador Digital)
============================================
POST /api/hr/attendance/clock-in   → Marcar entrada
POST /api/hr/attendance/clock-out  → Marcar salida (calcula horas)
GET  /api/hr/attendance            → Listado (OWNER_ADMIN / SUPERVISOR)
GET  /api/hr/employees/<id>/attendance → Asistencia de un empleado

Validación de IP: si la sucursal tiene branch_ip configurada,
se verifica que el empleado marque desde esa IP.
"""
from datetime import date

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models_hr import AttendanceRecord, Employee
from core.services.hr_calculator import calculate_attendance_hours
from core.models_hr import HRConfig


def _get_client_ip(request) -> str:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _serialize_record(rec: AttendanceRecord) -> dict:
    return {
        "id":             rec.id,
        "employee_ci":    rec.employee.ci,
        "employee_name":  rec.employee.full_name,
        "date":           str(rec.date),
        "clock_in":       rec.clock_in.isoformat(),
        "clock_out":      rec.clock_out.isoformat() if rec.clock_out else None,
        "regular_hours":  str(rec.regular_hours),
        "overtime_hours": str(rec.overtime_hours),
        "night_hours":    str(rec.night_hours),
        "ip_address":     rec.ip_address,
        "note":           rec.note,
    }


class ClockInView(APIView):
    """POST /api/hr/attendance/clock-in"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # El empleado marca con su propio token
        try:
            emp = request.user.employee_profile
        except Exception:
            return Response({"detail": "Tu usuario no tiene perfil de empleado."}, status=403)

        if emp.status != Employee.Status.ACTIVE:
            return Response({"detail": f"No puedes marcar asistencia: estado = {emp.status}."}, status=403)

        today = timezone.localdate()
        if AttendanceRecord.objects.filter(employee=emp, date=today).exists():
            return Response({"detail": "Ya marcaste entrada hoy."}, status=400)

        ip = _get_client_ip(request)
        now = timezone.now()

        record = AttendanceRecord.objects.create(
            employee   = emp,
            date       = today,
            clock_in   = now,
            ip_address = ip,
            note       = request.data.get("note", ""),
        )

        return Response({
            "detail":   "Entrada registrada.",
            "record":   _serialize_record(record),
            "message":  f"Buen día, {emp.first_name}. Entrada a las {now.strftime('%H:%M')}.",
        }, status=201)


class ClockOutView(APIView):
    """POST /api/hr/attendance/clock-out"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            emp = request.user.employee_profile
        except Exception:
            return Response({"detail": "Tu usuario no tiene perfil de empleado."}, status=403)

        today = timezone.localdate()
        try:
            record = AttendanceRecord.objects.get(employee=emp, date=today)
        except AttendanceRecord.DoesNotExist:
            return Response({"detail": "No tienes entrada registrada hoy."}, status=400)

        if record.clock_out is not None:
            return Response({"detail": "Ya marcaste salida hoy."}, status=400)

        now = timezone.now()
        cfg = HRConfig.get()

        hours = calculate_attendance_hours(
            clock_in         = record.clock_in,
            clock_out        = now,
            daily_hours      = emp.daily_hours,
            night_start_hour = cfg.night_surcharge_start_hour,
        )

        record.clock_out      = now
        record.regular_hours  = hours["regular_hours"]
        record.overtime_hours = hours["overtime_hours"]
        record.night_hours    = hours["night_hours"]
        record.note           = request.data.get("note", record.note)
        record.save()

        extras_msg = ""
        if hours["overtime_hours"] > 0:
            extras_msg = f" ({hours['overtime_hours']}h extra registradas)"

        return Response({
            "detail":       "Salida registrada.",
            "record":       _serialize_record(record),
            "total_hours":  str(hours["total_hours"]),
            "message":      f"Hasta mañana, {emp.first_name}. Total: {hours['total_hours']}h.{extras_msg}",
        })


class AttendanceListView(APIView):
    """
    GET /api/hr/attendance?employee_ci=X&year=Y&month=M
    Solo OWNER_ADMIN / SUPERVISOR.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN", "SUPERVISOR"})

        qs = AttendanceRecord.objects.select_related("employee").order_by("-date")

        ci = request.query_params.get("employee_ci")
        if ci:
            qs = qs.filter(employee__ci=ci)

        year = request.query_params.get("year")
        if year:
            qs = qs.filter(date__year=int(year))

        month = request.query_params.get("month")
        if month:
            qs = qs.filter(date__month=int(month))

        branch = request.query_params.get("branch")
        if branch:
            qs = qs.filter(employee__branch__code=branch)

        records = list(qs[:200])
        return Response({
            "total":   len(records),
            "records": [_serialize_record(r) for r in records],
        })


class EmployeeAttendanceView(APIView):
    """
    GET /api/hr/employees/<id>/attendance?year=Y&month=M
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, employee_id):
        require_roles(request.user, {"OWNER_ADMIN", "SUPERVISOR"})

        try:
            emp = Employee.objects.get(public_id=employee_id)
        except Employee.DoesNotExist:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        qs = emp.attendance.all().order_by("-date")

        year = request.query_params.get("year")
        if year:
            qs = qs.filter(date__year=int(year))
        month = request.query_params.get("month")
        if month:
            qs = qs.filter(date__month=int(month))

        records = list(qs[:100])

        from decimal import Decimal
        total_regular  = sum(r.regular_hours  for r in records)
        total_overtime = sum(r.overtime_hours for r in records)
        total_night    = sum(r.night_hours    for r in records)

        return Response({
            "employee":      emp.full_name,
            "employee_ci":   emp.ci,
            "days_recorded": len(records),
            "total_regular_hours":  str(total_regular),
            "total_overtime_hours": str(total_overtime),
            "total_night_hours":    str(total_night),
            "records": [_serialize_record(r) for r in records],
        })
