"""
Reporte de Cierre de Caja — PDF
================================
GET /api/cash-sessions/<cash_session_id>/closing-report.pdf

Secciones:
  1. Encabezado: caja, sucursal, cajero, fechas
  2. Arqueo: monto esperado, contado, diferencia
  3. Desglose del Turno: capital prestado/recuperado, utilidades, gastos
  4. Detalle de movimientos (todos los registros de la sesión)
  5. Línea de firmas
"""
from io import BytesIO
from decimal import Decimal

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

from core.models import CashSession, CashMovement
from core.models_security import UserRole
from core.services.cash_alerts import calculate_surplus


# ── Colores corporativos ──────────────────────────────────────────────────────
PRIMARY   = colors.HexColor("#1a3a5c")   # Azul oscuro
SECONDARY = colors.HexColor("#2d6a9f")   # Azul medio
ACCENT    = colors.HexColor("#e8f0f8")   # Fondo azul claro
SUCCESS   = colors.HexColor("#1e7e34")   # Verde
DANGER    = colors.HexColor("#c82333")   # Rojo
WARNING   = colors.HexColor("#856404")   # Amarillo-texto
GRAY_LIGHT= colors.HexColor("#f5f5f5")
GRAY_LINE = colors.HexColor("#cccccc")


def _fmt(value, prefix="Bs. ") -> str:
    try:
        return f"{prefix}{Decimal(str(value)):,.2f}"
    except Exception:
        return str(value)


def _diff_color(diff: Decimal) -> colors.Color:
    if diff > 0:
        return SUCCESS
    if diff < 0:
        return DANGER
    return colors.black


class CashSessionClosingReportPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cash_session_id):
        roles = set(
            UserRole.objects.filter(user=request.user)
            .values_list("role__code", flat=True)
        )
        if not roles.intersection({"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}):
            return HttpResponse(status=403)

        cash_session = get_object_or_404(
            CashSession.objects.select_related("cash_register", "cash_register__branch", "branch", "opened_by", "closed_by"),
            public_id=cash_session_id,
        )

        if "OWNER_ADMIN" not in roles and "SUPERVISOR" not in roles:
            if (cash_session.opened_by_id != request.user.id
                    and cash_session.closed_by_id != request.user.id):
                return HttpResponse(status=403)

        # ── Datos financieros ─────────────────────────────────────────────────
        surplus = calculate_surplus(cash_session)

        expected = cash_session.closing_expected_amount or cash_session.expected_balance
        counted  = cash_session.closing_counted_amount  or Decimal("0.00")
        diff     = cash_session.closing_diff_amount     or Decimal("0.00")

        movements = list(
            CashMovement.objects.filter(cash_session=cash_session)
            .order_by("performed_at")
            .select_related("performed_by")
        )

        # ── Construir PDF ─────────────────────────────────────────────────────
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=1.5 * cm,
            rightMargin=1.5 * cm,
            topMargin=1.5 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        story  = []

        # ── 1. Encabezado ─────────────────────────────────────────────────────
        header_data = [
            [
                Paragraph(
                    f"<font color='#{PRIMARY.hexval()[2:]}' size='16'><b>REPORTE DE CIERRE DE CAJA</b></font>",
                    styles["Normal"],
                ),
                Paragraph(
                    f"<font size='9' color='grey'>"
                    f"Sesión: {str(cash_session.public_id)[:8]}…<br/>"
                    f"Generado: {_now_str()}</font>",
                    ParagraphStyle("right", parent=styles["Normal"], alignment=TA_RIGHT),
                ),
            ]
        ]
        header_table = Table(header_data, colWidths=["65%", "35%"])
        header_table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 1.5, PRIMARY),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 0.4 * cm))

        # Datos de la sesión
        branch_name = cash_session.branch.code if cash_session.branch else "GLOBAL"
        info_data = [
            ["Caja:",        cash_session.cash_register.name,
             "Sucursal:",    branch_name],
            ["Apertura:",    _dt(cash_session.opened_at),
             "Cajero:",      str(cash_session.opened_by)],
            ["Cierre:",      _dt(cash_session.closed_at) if cash_session.closed_at else "—",
             "Cerrado por:", str(cash_session.closed_by) if cash_session.closed_by else "—"],
        ]
        info_table = Table(info_data, colWidths=["18%", "32%", "18%", "32%"])
        info_table.setStyle(TableStyle([
            ("FONTNAME",    (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE",    (0, 0), (-1, -1), 9),
            ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME",    (2, 0), (2, -1), "Helvetica-Bold"),
            ("TEXTCOLOR",   (0, 0), (0, -1), PRIMARY),
            ("TEXTCOLOR",   (2, 0), (2, -1), PRIMARY),
            ("BACKGROUND",  (0, 0), (-1, -1), ACCENT),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [ACCENT, GRAY_LIGHT]),
            ("GRID",        (0, 0), (-1, -1), 0.25, GRAY_LINE),
            ("TOPPADDING",  (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.5 * cm))

        # ── 2. Arqueo ─────────────────────────────────────────────────────────
        story.append(_section_title("ARQUEO DE CAJA", styles))

        diff_color_hex = SUCCESS.hexval() if diff >= 0 else DANGER.hexval()
        diff_label     = "SOBRANTE" if diff > 0 else ("FALTANTE" if diff < 0 else "CUADRADO")

        arqueo_data = [
            ["Concepto", "Monto"],
            ["Monto Esperado (sistema)", _fmt(expected)],
            ["Monto Contado (físico)",   _fmt(counted)],
            [f"Diferencia — {diff_label}",
             Paragraph(f"<font color='#{diff_color_hex[2:]}'><b>{_fmt(diff)}</b></font>", styles["Normal"])],
        ]
        arqueo_table = Table(arqueo_data, colWidths=["60%", "40%"])
        arqueo_table.setStyle(TableStyle([
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 9),
            ("BACKGROUND",   (0, 0), (-1, 0), PRIMARY),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRAY_LIGHT]),
            ("GRID",         (0, 0), (-1, -1), 0.25, GRAY_LINE),
            ("ALIGN",        (1, 0), (1, -1), "RIGHT"),
            ("RIGHTPADDING", (1, 0), (1, -1), 10),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(arqueo_table)
        story.append(Spacer(1, 0.5 * cm))

        # ── 3. Desglose del Turno ─────────────────────────────────────────────
        story.append(_section_title("DESGLOSE DEL TURNO", styles))

        desglose_data = [
            ["Concepto", "Monto", "Descripción"],
            # Apertura
            ["Saldo de apertura", _fmt(surplus["opening_amount"]), "Fondo inicial del turno"],
            # Ingresos
            ["Pagos recibidos (total)", _fmt(surplus["payment_in"]), "CC / UC cobrados"],
            ["  └ Capital recuperado",  _fmt(surplus["capital_recovered"]), "Devolución de préstamos"],
            ["  └ Utilidades (interés)", _fmt(surplus["profit_earned"]), "Ganancia del turno (UC)"],
            ["Ingresos por transferencia", _fmt(surplus["transfer_in"]), "Desde bóveda / traslados"],
            # Egresos
            ["Préstamos desembolsados", _fmt(surplus["loan_out"]), "CN — Contratos nuevos"],
            ["Compras directas",         _fmt(surplus["purchase_out"]), "CD — Compras"],
            ["Gastos operativos",         _fmt(surplus["expense_out"]), "G — Gastos"],
            ["Egresos por transferencia", _fmt(surplus["transfer_out"]), "Hacia bóveda / traslados"],
            # Resultado
            ["Saldo final (sistema)",     _fmt(surplus["current_balance"]), ""],
            ["Flujo neto del turno",       _fmt(surplus["net_surplus"]), "Vs. apertura"],
        ]

        desglose_table = Table(desglose_data, colWidths=["38%", "22%", "40%"])
        desglose_table.setStyle(TableStyle([
            # Encabezado
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, 0), 9),
            ("BACKGROUND",   (0, 0), (-1, 0), SECONDARY),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            # Cuerpo
            ("FONTSIZE",     (0, 1), (-1, -1), 8),
            ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRAY_LIGHT]),
            # Resaltar filas de resultado
            ("BACKGROUND",   (0, -2), (-1, -1), ACCENT),
            ("FONTNAME",     (0, -2), (-1, -1), "Helvetica-Bold"),
            # Líneas
            ("GRID",         (0, 0), (-1, -1), 0.25, GRAY_LINE),
            ("LINEABOVE",    (0, -2), (-1, -2), 1, PRIMARY),
            # Padding
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ("ALIGN",        (1, 0), (1, -1), "RIGHT"),
            ("RIGHTPADDING", (1, 0), (1, -1), 8),
        ]))
        story.append(desglose_table)
        story.append(Spacer(1, 0.5 * cm))

        # ── 4. Detalle de movimientos ─────────────────────────────────────────
        story.append(_section_title("DETALLE DE MOVIMIENTOS", styles))

        mov_data = [["Fecha/Hora", "Tipo", "Monto", "Nota"]]
        total_in  = Decimal("0.00")
        total_out = Decimal("0.00")

        for m in movements:
            mt = m.movement_type.upper()
            if mt.endswith("_IN"):
                total_in  += m.amount
                sign_color = SUCCESS.hexval()
            else:
                total_out += m.amount
                sign_color = DANGER.hexval()

            mov_data.append([
                _dt(m.performed_at)[:16],
                _type_label(m.movement_type),
                Paragraph(
                    f"<font color='#{sign_color[2:]}'>{_fmt(m.amount)}</font>",
                    styles["Normal"]
                ),
                (m.note or "")[:55],
            ])

        # Fila de totales
        mov_data.append([
            "", "TOTALES",
            Paragraph(
                f"<b><font color='#{SUCCESS.hexval()[2:]}'>+{_fmt(total_in)}</font><br/>"
                f"<font color='#{DANGER.hexval()[2:]}'>-{_fmt(total_out)}</font></b>",
                styles["Normal"]
            ),
            "",
        ])

        mov_table = Table(mov_data, colWidths=["22%", "24%", "20%", "34%"])
        mov_table.setStyle(TableStyle([
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS",(0, 1), (-1, -2), [colors.white, GRAY_LIGHT]),
            ("BACKGROUND",    (0, -1), (-1, -1), ACCENT),
            ("FONTNAME",      (0, -1), (-1, -1), "Helvetica-Bold"),
            ("GRID",          (0, 0), (-1, -1), 0.25, GRAY_LINE),
            ("LINEABOVE",     (0, -1), (-1, -1), 1, PRIMARY),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("ALIGN",         (2, 0), (2, -1), "RIGHT"),
        ]))
        story.append(mov_table)
        story.append(Spacer(1, 1 * cm))

        # ── 5. Firmas ─────────────────────────────────────────────────────────
        firma_data = [[
            Paragraph("<br/><br/>______________________________<br/><b>Cajero</b>", styles["Normal"]),
            Paragraph("<br/><br/>______________________________<br/><b>Supervisor</b>", styles["Normal"]),
        ]]
        firma_table = Table(firma_data, colWidths=["50%", "50%"])
        firma_table.setStyle(TableStyle([
            ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(firma_table)

        # ── Build ─────────────────────────────────────────────────────────────
        doc.build(story)
        pdf = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="cierre_{cash_session.public_id}.pdf"'
        )
        return response


# ── Helpers ───────────────────────────────────────────────────────────────────
def _section_title(text: str, styles) -> Paragraph:
    style = ParagraphStyle(
        "section",
        parent=styles["Normal"],
        fontSize=10,
        fontName="Helvetica-Bold",
        textColor=PRIMARY,
        spaceAfter=4,
        spaceBefore=4,
        borderPad=2,
        borderColor=PRIMARY,
        borderWidth=0,
        leftIndent=0,
    )
    return Paragraph(f'<u>{text}</u>', style)


def _dt(dt) -> str:
    if dt is None:
        return "—"
    import pytz
    try:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt)


def _now_str() -> str:
    from django.utils import timezone
    return timezone.now().strftime("%Y-%m-%d %H:%M")


_MOVEMENT_LABELS = {
    "TRANSFER_IN":    "Transferencia entrada",
    "TRANSFER_OUT":   "Transferencia salida",
    "ADJUSTMENT_IN":  "Ajuste sobrante",
    "ADJUSTMENT_OUT": "Ajuste faltante",
    "LOAN_OUT":       "CN — Préstamo",
    "PAYMENT_IN":     "CC/UC — Cobro",
    "PURCHASE_OUT":   "CD — Compra directa",
    "EXPENSE_OUT":    "G — Gasto operativo",
    "VAULT_IN":       "Ingreso bóveda",
    "VAULT_OUT":      "Salida bóveda",
}


def _type_label(movement_type: str) -> str:
    return _MOVEMENT_LABELS.get(movement_type, movement_type)
