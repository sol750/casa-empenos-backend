from io import BytesIO
from datetime import datetime, time

from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from core.api.serializers.report_daily_summary import DailySummaryQuerySerializer
from core.models import Branch, CashRegister, CashSession, CashMovement
from core.models_security import UserRole, UserBranchAccess


class DailySummaryReportPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = DailySummaryQuerySerializer(data=request.query_params)
        qs.is_valid(raise_exception=True)

        branch_code = qs.validated_data["branch_code"]
        report_date = qs.validated_data.get("date")

        tz = timezone.get_current_timezone()
        if report_date is None:
            report_date = timezone.localdate()

        start_dt = timezone.make_aware(datetime.combine(report_date, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(report_date, time.max), tz)

        try:
            branch = Branch.objects.get(code=branch_code)
        except Branch.DoesNotExist:
            return Response({"detail": "Sucursal no existe."}, status=404)

        # Permisos
        roles = set(
            UserRole.objects.filter(user=request.user)
            .values_list("role__code", flat=True)
        )

        if "OWNER_ADMIN" not in roles:
            has_access = UserBranchAccess.objects.filter(user=request.user, branch=branch).exists()
            if not has_access:
                return Response({"detail": "No tiene acceso a esta sucursal."}, status=403)

        registers = CashRegister.objects.filter(branch=branch, is_active=True).order_by("name")
        sessions = (
            CashSession.objects
            .filter(branch=branch, status=CashSession.Status.CLOSED, closed_at__gte=start_dt, closed_at__lte=end_dt)
            .select_related("cash_register", "closed_by")
            .order_by("closed_at")
        )

        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - 50

        # Título
        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, y, "REPORTE DIARIO DE CAJA (SUCURSAL)")
        y -= 20
        p.setFont("Helvetica", 10)
        p.drawString(50, y, f"Sucursal: {branch.code} - {branch.name}")
        y -= 14
        p.drawString(50, y, f"Fecha: {report_date}   Rango: {start_dt} a {end_dt}")
        y -= 20

        # Resumen por caja
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, "Resumen por Caja")
        y -= 14
        p.setFont("Helvetica-Bold", 9)
        p.drawString(50, y, "Caja")
        p.drawString(220, y, "Total IN")
        p.drawString(300, y, "Total OUT")
        p.drawString(390, y, "Últ. Diff")
        y -= 10
        p.line(50, y, 560, y)
        y -= 12

        p.setFont("Helvetica", 9)
        for reg in registers:
            movements = CashMovement.objects.filter(
                cash_register=reg,
                performed_at__gte=start_dt,
                performed_at__lte=end_dt,
            )
            total_in = movements.filter(movement_type__endswith="_IN").aggregate(s=Sum("amount"))["s"] or 0
            total_out = movements.filter(movement_type__endswith="_OUT").aggregate(s=Sum("amount"))["s"] or 0

            operation_in = movements.filter(movement_type=CashMovement.MovementType.PAYMENT_IN).aggregate(s=Sum("amount"))["s"] or 0
            operation_out = movements.filter(movement_type=CashMovement.MovementType.LOAN_OUT).aggregate(s=Sum("amount"))["s"] or 0

            transfers_in = movements.filter(movement_type=CashMovement.MovementType.TRANSFER_IN).aggregate(s=Sum("amount"))["s"] or 0
            transfers_out = movements.filter(movement_type=CashMovement.MovementType.TRANSFER_OUT).aggregate(s=Sum("amount"))["s"] or 0

            adjustments_in = movements.filter(movement_type=CashMovement.MovementType.ADJUSTMENT_IN).aggregate(s=Sum("amount"))["s"] or 0
            adjustments_out = movements.filter(movement_type=CashMovement.MovementType.ADJUSTMENT_OUT).aggregate(s=Sum("amount"))["s"] or 0

            last_closed = sessions.filter(cash_register=reg).order_by("-closed_at").first()
            last_diff = "—" if not last_closed else str(last_closed.closing_diff_amount or "0.00")

            if y < 120:
                p.showPage()
                y = height - 50

            p.drawString(50, y, reg.name)
            p.drawRightString(270, y, str(total_in))
            p.drawRightString(350, y, str(total_out))
            p.drawRightString(460, y, last_diff)
            y -= 12
            if y < 120:
                p.showPage()
                y = height - 50

            p.setFont("Helvetica", 8)
            alert_text = ""
            if adjustments_out > 0:
                alert_text += "  ***ALERTA FALTANTE***"
            if adjustments_in > 0:
                alert_text += "  ***ALERTA SOBRANTE***"
            p.drawString(
                60,
                y,
                f"Operación IN:{operation_in} OUT:{operation_out}  |  Transfer IN:{transfers_in} OUT:{transfers_out}  |  Ajustes IN:{adjustments_in} OUT:{adjustments_out}{alert_text}"
            )
            p.setFont("Helvetica", 9)
            y -= 12


        y -= 10

        # Sesiones cerradas
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, "Sesiones Cerradas del Día")
        y -= 14
        p.setFont("Helvetica-Bold", 9)
        p.drawString(50, y, "Caja")
        p.drawString(160, y, "Cierre")
        p.drawString(280, y, "Expected")
        p.drawString(360, y, "Counted")
        p.drawString(440, y, "Diff")
        y -= 10
        p.line(50, y, 560, y)
        y -= 12
        p.setFont("Helvetica", 9)

        if not sessions.exists():
            p.drawString(50, y, "No hay sesiones cerradas en este día.")
            y -= 12
        else:
            for s in sessions:
                if y < 80:
                    p.showPage()
                    y = height - 50

                diff = s.closing_diff_amount or 0
                flag = "" if diff == 0 else "ALERTA"
             
                p.drawString(50, y, s.cash_register.name)
                p.drawString(160, y, str(s.closed_at)[:19])
                p.drawRightString(330, y, str(s.closing_expected_amount or "0.00"))
                p.drawRightString(410, y, str(s.closing_counted_amount or "0.00"))
                p.drawRightString(480, y, str(s.closing_diff_amount or "0.00"))
                p.drawRightString(540, y, flag)
                y -= 12
                
        # Firma
        y -= 25
        p.setFont("Helvetica", 10)
        p.drawString(50, y, "Firma Supervisor: _______________________")
        p.drawString(320, y, "Firma Dueño: _______________________")

        p.showPage()
        p.save()

        pdf = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="reporte_diario_{branch.code}_{report_date}.pdf"'
        return response
