from io import BytesIO
from decimal import Decimal
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from core.models import CashSession, CashMovement
from core.models_security import UserRole


class CashSessionClosingReportPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cash_session_id):
        # permisos: cajero puede ver su sesión, supervisor/owner todo
        roles = set(
            UserRole.objects.filter(user=request.user)
            .values_list("role__code", flat=True)
        )
        if not roles.intersection({"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}):
            return HttpResponse(status=403)

        cash_session = get_object_or_404(CashSession, public_id=cash_session_id)

        # (opcional) restricción por sucursal si no es dueño/supervisor
        if "OWNER_ADMIN" not in roles and "SUPERVISOR" not in roles:
            if cash_session.opened_by_id != request.user.id and cash_session.closed_by_id != request.user.id:
                return HttpResponse(status=403)

        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        y = height - 50
        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, y, "REPORTE DE CIERRE DE CAJA")
        y -= 25

        p.setFont("Helvetica", 10)
        p.drawString(50, y, f"Caja: {cash_session.cash_register.name}  ({cash_session.cash_register.register_type})")
        y -= 15
        p.drawString(50, y, f"Sucursal: {cash_session.branch.code if cash_session.branch else 'GLOBAL'}")
        y -= 15
        p.drawString(50, y, f"Apertura: {cash_session.opened_at}  Monto: {cash_session.opening_amount}")
        y -= 15
        p.drawString(50, y, f"Cierre: {cash_session.closed_at}  Por: {cash_session.closed_by}")
        y -= 20

        expected = cash_session.closing_expected_amount or Decimal("0.00")
        counted = cash_session.closing_counted_amount or Decimal("0.00")
        diff = cash_session.closing_diff_amount or Decimal("0.00")

        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y, f"Expected: {expected}   Counted: {counted}   Diff: {diff}")
        y -= 20

        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y, "Movimientos")
        y -= 15

        p.setFont("Helvetica", 9)
        p.drawString(50, y, "Fecha")
        p.drawString(160, y, "Tipo")
        p.drawString(310, y, "Monto")
        p.drawString(380, y, "Nota")
        y -= 10
        p.line(50, y, 560, y)
        y -= 12

        movements = CashMovement.objects.filter(cash_session=cash_session).order_by("performed_at")

        total_in = Decimal("0.00")
        total_out = Decimal("0.00")

        for m in movements:
            mt = (m.movement_type or "").upper().strip()
            if mt.endswith("_IN"):
                total_in += m.amount
            elif mt.endswith("_OUT"):
                total_out += m.amount

            if y < 80:
                p.showPage()
                y = height - 50

            p.drawString(50, y, str(m.performed_at)[:19])
            p.drawString(160, y, m.movement_type)
            p.drawRightString(350, y, str(m.amount))
            p.drawString(380, y, (m.note or "")[:40])
            y -= 12

        y -= 10
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y, f"Totales  IN: {total_in}    OUT: {total_out}")
        y -= 30

        p.setFont("Helvetica", 10)
        p.drawString(50, y, "Firma Cajero: _______________________")
        p.drawString(320, y, "Firma Supervisor: _______________________")

        p.showPage()
        p.save()

        pdf = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="cierre_caja_{cash_session.public_id}.pdf"'
        return response
