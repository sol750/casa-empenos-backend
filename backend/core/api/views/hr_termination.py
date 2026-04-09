"""
RRHH — Baja de Empleado y Liquidación
=======================================
POST /api/hr/employees/<id>/terminate   → Dar de baja + calcular liquidación
GET  /api/hr/employees/<id>/terminate   → Ver liquidación calculada

Al dar de baja:
  1. Se calcula la liquidación tentativa (indemnización + aguinaldo + vacaciones)
  2. Se cambia employee.status = TERMINATED
  3. Se deshabilita el usuario del sistema (user.is_active = False)
     → Bloquea acceso inmediato a cajas y al software

También se genera el log de auditoría consultando todas las
acciones del empleado en el sistema (contratos, pagos, movimientos de caja).
"""
from datetime import date

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models_hr import Employee, EmployeeTermination
from core.services.hr_calculator import calculate_liquidation


def _serialize_termination(t: EmployeeTermination) -> dict:
    return {
        "employee_ci":            t.employee.ci,
        "employee_name":          t.employee.full_name,
        "termination_date":       str(t.termination_date),
        "reason":                 t.reason,
        "months_worked":          t.months_worked,
        "base_salary_snapshot":   str(t.base_salary_snapshot),
        "indemnization_months":   str(t.indemnization_months),
        "indemnization_amount":   str(t.indemnization_amount),
        "aguinaldo_months":       str(t.aguinaldo_months),
        "aguinaldo_amount":       str(t.aguinaldo_amount),
        "unused_vacation_days":   t.unused_vacation_days,
        "unused_vacation_amount": str(t.unused_vacation_amount),
        "total_liquidation":      str(t.total_liquidation),
        "notes":                  t.notes,
        "created_at":             t.created_at.isoformat(),
        "certificate_generated":  bool(t.certificate_generated_at),
    }


class EmployeeTerminationView(APIView):
    """
    GET  /api/hr/employees/<id>/terminate → preview de liquidación (sin guardar)
    POST /api/hr/employees/<id>/terminate → confirmar baja y guardar
    """
    permission_classes = [IsAuthenticated]

    def _get_emp(self, employee_id):
        try:
            return Employee.objects.select_related("user").prefetch_related(
                "vacations"
            ).get(public_id=employee_id)
        except Employee.DoesNotExist:
            return None

    def get(self, request, employee_id):
        """Preview de la liquidación SIN guardar cambios."""
        require_roles(request.user, {"OWNER_ADMIN"})
        emp = self._get_emp(employee_id)
        if not emp:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        if emp.status == Employee.Status.TERMINATED:
            try:
                return Response(_serialize_termination(emp.termination))
            except Exception:
                pass

        reason = request.query_params.get("reason", "VOLUNTARY")
        term_date = date.today()
        calc = calculate_liquidation(emp, term_date, reason)

        return Response({
            "preview":          True,
            "employee_ci":      emp.ci,
            "employee_name":    emp.full_name,
            "termination_date": str(term_date),
            "reason":           reason,
            **{k: str(v) if hasattr(v, "quantize") else v for k, v in calc.items()},
        })

    def post(self, request, employee_id):
        """Confirmar baja. Acción irreversible — deshabilita acceso al instante."""
        require_roles(request.user, {"OWNER_ADMIN"})
        emp = self._get_emp(employee_id)
        if not emp:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        if emp.status == Employee.Status.TERMINATED:
            return Response({"detail": "El empleado ya fue dado de baja."}, status=400)

        d = request.data
        reason    = d.get("reason", "VOLUNTARY").upper()
        term_date_str = d.get("termination_date", str(date.today()))
        try:
            term_date = date.fromisoformat(term_date_str)
        except ValueError:
            return Response({"detail": "Formato de fecha inválido (YYYY-MM-DD)."}, status=400)

        valid_reasons = [r[0] for r in EmployeeTermination.Reason.choices]
        if reason not in valid_reasons:
            return Response({"detail": f"Razón inválida. Opciones: {valid_reasons}"}, status=400)

        calc = calculate_liquidation(emp, term_date, reason)

        # ── 1. Guardar liquidación ─────────────────────────────────────────────
        termination = EmployeeTermination.objects.create(
            employee              = emp,
            termination_date      = term_date,
            reason                = reason,
            created_by            = request.user,
            notes                 = d.get("notes", ""),
            **calc,
        )

        # ── 2. Cambiar estado del empleado ────────────────────────────────────
        emp.status = Employee.Status.TERMINATED
        emp.save(update_fields=["status", "updated_at"])

        # ── 3. Deshabilitar acceso al sistema INMEDIATAMENTE ─────────────────
        emp.user.is_active = False
        emp.user.save(update_fields=["is_active"])

        return Response({
            "detail":      "Empleado dado de baja. Acceso al sistema bloqueado.",
            "termination": _serialize_termination(termination),
        }, status=201)


class EmployeeAuditLogView(APIView):
    """
    GET /api/hr/employees/<id>/audit-log?days=30

    Muestra las acciones del empleado en el sistema:
    contratos creados, pagos procesados, movimientos de caja,
    transferencias realizadas y registros de asistencia.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, employee_id):
        require_roles(request.user, {"OWNER_ADMIN", "SUPERVISOR"})

        try:
            emp = Employee.objects.select_related("user").get(public_id=employee_id)
        except Employee.DoesNotExist:
            return Response({"detail": "Empleado no encontrado."}, status=404)

        user = emp.user
        days = int(request.query_params.get("days", 30))
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=days)

        events = []

        # Contratos creados
        from core.models import PawnContract
        for c in PawnContract.objects.filter(created_by=user, created_at__gte=cutoff).order_by("-created_at")[:50]:
            events.append({
                "type":        "CONTRATO_CREADO",
                "timestamp":   c.created_at.isoformat(),
                "description": f"Creó contrato {c.contract_number} — Bs.{c.principal_amount}",
                "ref":         c.contract_number,
            })

        # Pagos procesados
        from core.models import PawnPayment
        for p in PawnPayment.objects.filter(paid_by=user, paid_at__gte=cutoff).select_related("contract").order_by("-paid_at")[:50]:
            events.append({
                "type":        "PAGO_PROCESADO",
                "timestamp":   p.paid_at.isoformat(),
                "description": f"Cobró Bs.{p.amount} al contrato {p.contract.contract_number}",
                "ref":         p.contract.contract_number,
            })

        # Movimientos de caja
        from core.models import CashMovement
        for m in CashMovement.objects.filter(performed_by=user, performed_at__gte=cutoff).order_by("-performed_at")[:100]:
            events.append({
                "type":        "MOVIMIENTO_CAJA",
                "timestamp":   m.performed_at.isoformat(),
                "description": f"{m.movement_type} Bs.{m.amount} — {m.note or '—'}",
                "ref":         str(m.public_id)[:8],
            })

        # Sesiones de caja abiertas
        from core.models import CashSession
        for s in CashSession.objects.filter(opened_by=user, opened_at__gte=cutoff).order_by("-opened_at")[:20]:
            events.append({
                "type":        "SESION_ABIERTA",
                "timestamp":   s.opened_at.isoformat(),
                "description": f"Abrió caja {s.cash_register.name} con Bs.{s.opening_amount}",
                "ref":         str(s.public_id)[:8],
            })

        # Asistencia
        from core.models_hr import AttendanceRecord
        for a in AttendanceRecord.objects.filter(employee=emp, clock_in__gte=cutoff).order_by("-clock_in")[:30]:
            out = a.clock_out.strftime("%H:%M") if a.clock_out else "—"
            events.append({
                "type":        "ASISTENCIA",
                "timestamp":   a.clock_in.isoformat(),
                "description": f"Entrada {a.clock_in.strftime('%H:%M')} / Salida {out} | extras: {a.overtime_hours}h",
                "ref":         str(a.date),
            })

        # Ordenar todo por timestamp desc
        events.sort(key=lambda x: x["timestamp"], reverse=True)

        return Response({
            "employee":      emp.full_name,
            "employee_ci":   emp.ci,
            "period_days":   days,
            "total_events":  len(events),
            "events":        events[:200],
        })
