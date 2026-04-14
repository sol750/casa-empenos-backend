"""
Fase de Sincronización — Digitalización de Contratos Históricos 2023-2025
=========================================================================

GET  /api/sync/balance-adjustments?branch=PT1
POST /api/sync/balance-adjustments
     Body: { branch_code, adjustment_date, book_balance, note }
     → Registra el saldo físico del libro para una fecha dada

DELETE /api/sync/balance-adjustments/<uuid:adjustment_id>
     → Elimina un ajuste (solo OWNER_ADMIN)

GET  /api/sync/book-reconciliation?branch=PT1&from=2024-01-01&to=2024-12-31
     → Reporte de conciliación: [Saldo Sistema] vs [Saldo Libro Físico]

Solo accesible para OWNER_ADMIN.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models import Branch, CashMovement, LegacyBalanceAdjustment


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _system_balance_for_range(branch: Branch, from_date: date, to_date: date) -> Decimal:
    """
    Calcula el saldo neto del sistema para una sucursal en un rango de fechas,
    usando effective_date cuando está disponible, o performed_at.date() como
    fallback para movimientos sin fecha retroactiva.
    """
    qs = CashMovement.objects.filter(branch=branch)

    # Movimientos con effective_date explícita (retroactivos)
    retro_in = (
        qs.filter(
            effective_date__gte=from_date,
            effective_date__lte=to_date,
            movement_type__endswith="_IN",
        ).aggregate(t=Sum("amount"))["t"]
    ) or Decimal("0.00")

    retro_out = (
        qs.filter(
            effective_date__gte=from_date,
            effective_date__lte=to_date,
            movement_type__endswith="_OUT",
        ).aggregate(t=Sum("amount"))["t"]
    ) or Decimal("0.00")

    # Movimientos normales sin effective_date (usamos performed_at)
    normal_in = (
        qs.filter(
            effective_date__isnull=True,
            performed_at__date__gte=from_date,
            performed_at__date__lte=to_date,
            movement_type__endswith="_IN",
        ).aggregate(t=Sum("amount"))["t"]
    ) or Decimal("0.00")

    normal_out = (
        qs.filter(
            effective_date__isnull=True,
            performed_at__date__gte=from_date,
            performed_at__date__lte=to_date,
            movement_type__endswith="_OUT",
        ).aggregate(t=Sum("amount"))["t"]
    ) or Decimal("0.00")

    return (retro_in + normal_in) - (retro_out + normal_out)


# ─────────────────────────────────────────────────────────────────────────────
# Vista: Ajustes de Saldo
# ─────────────────────────────────────────────────────────────────────────────

class SyncBalanceAdjustmentView(APIView):
    """
    GET  /api/sync/balance-adjustments?branch=PT1
    POST /api/sync/balance-adjustments
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        branch_code = request.query_params.get("branch")
        qs = LegacyBalanceAdjustment.objects.select_related("branch", "created_by")
        if branch_code:
            qs = qs.filter(branch__code=branch_code.upper())

        return Response({
            "total": qs.count(),
            "adjustments": [
                {
                    "adjustment_id":   str(adj.public_id),
                    "branch":          adj.branch.code,
                    "adjustment_date": str(adj.adjustment_date),
                    "book_balance":    str(adj.book_balance),
                    "note":            adj.note,
                    "created_by":      adj.created_by.username,
                    "created_at":      adj.created_at.isoformat(),
                }
                for adj in qs
            ],
        })

    def post(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        d = request.data

        # Validación de campos requeridos
        missing = [f for f in ("branch_code", "adjustment_date", "book_balance") if not d.get(f)]
        if missing:
            return Response({"detail": "Campos requeridos.", "missing": missing}, status=400)

        try:
            branch = Branch.objects.get(code=d["branch_code"].upper())
        except Branch.DoesNotExist:
            return Response({"detail": "Sucursal no encontrada."}, status=400)

        try:
            adj_date = date.fromisoformat(str(d["adjustment_date"]))
        except ValueError:
            return Response({"detail": "adjustment_date debe ser formato YYYY-MM-DD."}, status=400)

        if adj_date > timezone.now().date():
            return Response({"detail": "La fecha del ajuste no puede ser futura."}, status=400)

        try:
            book_balance = Decimal(str(d["book_balance"]))
        except Exception:
            return Response({"detail": "book_balance debe ser un número válido."}, status=400)

        if book_balance < 0:
            return Response({"detail": "El saldo del libro no puede ser negativo."}, status=400)

        # Upsert: si ya existe para esa sucursal/fecha, actualizar
        adj, created = LegacyBalanceAdjustment.objects.update_or_create(
            branch=branch,
            adjustment_date=adj_date,
            defaults={
                "book_balance": book_balance,
                "note":         d.get("note", ""),
                "created_by":   request.user,
            },
        )

        return Response(
            {
                "detail": "Ajuste registrado." if created else "Ajuste actualizado.",
                "adjustment_id":   str(adj.public_id),
                "branch":          branch.code,
                "adjustment_date": str(adj.adjustment_date),
                "book_balance":    str(adj.book_balance),
            },
            status=201 if created else 200,
        )


class SyncBalanceAdjustmentDeleteView(APIView):
    """DELETE /api/sync/balance-adjustments/<uuid:adjustment_id>"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, adjustment_id):
        require_roles(request.user, {"OWNER_ADMIN"})
        try:
            adj = LegacyBalanceAdjustment.objects.get(public_id=adjustment_id)
        except LegacyBalanceAdjustment.DoesNotExist:
            return Response({"detail": "Ajuste no encontrado."}, status=404)

        adj.delete()
        return Response({"detail": "Ajuste eliminado."}, status=200)


# ─────────────────────────────────────────────────────────────────────────────
# Vista: Reporte de Conciliación de Libros
# ─────────────────────────────────────────────────────────────────────────────

class SyncBookReconciliationView(APIView):
    """
    GET /api/sync/book-reconciliation?branch=PT1&from=2024-01-01&to=2024-12-31

    Retorna una tabla mes a mes con:
      - system_net:   flujo neto calculado por el sistema para ese mes
      - book_balance: saldo ingresado manualmente del libro físico
      - difference:   system_net - book_balance  (positivo = sistema tiene más)
      - status:       OK | DISCREPANCY | NO_BOOK_ENTRY
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN", "SUPERVISOR"})

        branch_code = request.query_params.get("branch")
        from_str    = request.query_params.get("from")
        to_str      = request.query_params.get("to")

        if not branch_code:
            return Response({"detail": "Parámetro requerido: ?branch=<código>"}, status=400)

        try:
            branch = Branch.objects.get(code=branch_code.upper())
        except Branch.DoesNotExist:
            return Response({"detail": "Sucursal no encontrada."}, status=400)

        # Defaults: todo el año 2024 si no se especifica
        try:
            from_date = date.fromisoformat(from_str) if from_str else date(2023, 1, 1)
            to_date   = date.fromisoformat(to_str)   if to_str   else date(2025, 12, 31)
        except ValueError:
            return Response({"detail": "from y to deben ser formato YYYY-MM-DD."}, status=400)

        if from_date > to_date:
            return Response({"detail": "La fecha 'from' debe ser anterior a 'to'."}, status=400)

        # Cargar todos los ajustes del libro para esta sucursal en el rango
        adjustments = {
            adj.adjustment_date: adj.book_balance
            for adj in LegacyBalanceAdjustment.objects.filter(
                branch=branch,
                adjustment_date__gte=from_date,
                adjustment_date__lte=to_date,
            )
        }

        # Iterar mes a mes
        rows = []
        total_system   = Decimal("0.00")
        total_book     = Decimal("0.00")
        total_diff     = Decimal("0.00")
        discrepancies  = 0

        current = date(from_date.year, from_date.month, 1)
        while current <= to_date:
            # Último día del mes
            if current.month == 12:
                month_end = date(current.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(current.year, current.month + 1, 1) - timedelta(days=1)

            # Recortar al rango solicitado
            period_start = max(current, from_date)
            period_end   = min(month_end, to_date)

            system_net = _system_balance_for_range(branch, period_start, period_end)

            # Buscar entrada de libro más cercana en este mes
            book_entry  = None
            book_balance = None
            for d_key in sorted(adjustments.keys()):
                if period_start <= d_key <= period_end:
                    book_entry   = str(d_key)
                    book_balance = adjustments[d_key]
                    break

            if book_balance is not None:
                diff         = system_net - book_balance
                row_status   = "OK" if abs(diff) <= Decimal("0.01") else "DISCREPANCY"
                total_book  += book_balance
                total_diff  += diff
                if row_status == "DISCREPANCY":
                    discrepancies += 1
            else:
                diff       = None
                row_status = "NO_BOOK_ENTRY"

            total_system += system_net

            rows.append({
                "period":        f"{current.year}-{current.month:02d}",
                "period_start":  str(period_start),
                "period_end":    str(period_end),
                "system_net":    str(system_net),
                "book_entry_date": book_entry,
                "book_balance":  str(book_balance) if book_balance is not None else None,
                "difference":    str(diff) if diff is not None else None,
                "status":        row_status,
            })

            # Avanzar al siguiente mes
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        return Response({
            "branch":       branch.code,
            "from":         str(from_date),
            "to":           str(to_date),
            "summary": {
                "total_system_net":  str(total_system),
                "total_book":        str(total_book),
                "total_difference":  str(total_diff),
                "discrepancy_months": discrepancies,
                "months_without_book_entry": sum(
                    1 for r in rows if r["status"] == "NO_BOOK_ENTRY"
                ),
                "sync_health": (
                    "OK" if discrepancies == 0
                    else "WARNING" if discrepancies <= 2
                    else "ALERT"
                ),
            },
            "monthly_rows": rows,
        })
