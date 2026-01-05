from datetime import datetime, time
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.serializers.report_daily_summary import DailySummaryQuerySerializer
from core.models import Branch, CashRegister, CashSession, CashMovement
from core.models_security import UserRole, UserBranchAccess


class DailySummaryReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = DailySummaryQuerySerializer(data=request.query_params)
        qs.is_valid(raise_exception=True)

        branch_code = qs.validated_data["branch_code"]
        report_date = qs.validated_data.get("date")

        # Si no mandan date: hoy (timezone local)
        tz = timezone.get_current_timezone()
        if report_date is None:
            report_date = timezone.localdate()

        # rango del día [00:00, 23:59:59]
        start_dt = timezone.make_aware(datetime.combine(report_date, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(report_date, time.max), tz)

        # Branch
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
            # supervisor/cajero debe tener acceso a sucursal
            has_access = UserBranchAccess.objects.filter(user=request.user, branch=branch).exists()
            if not has_access:
                return Response({"detail": "No tiene acceso a esta sucursal."}, status=403)

        # Cajas de la sucursal (BRANCH)
        registers = CashRegister.objects.filter(branch=branch, is_active=True).order_by("name")

        registers_summary = []
        sessions_summary = []
        transfers_summary = []

        # Sesiones cerradas en el día (por sucursal)
        sessions = (
            CashSession.objects
            .filter(branch=branch, status=CashSession.Status.CLOSED, closed_at__gte=start_dt, closed_at__lte=end_dt)
            .select_related("cash_register", "closed_by")
            .order_by("closed_at")
        )

        # Lista sesiones
        for s in sessions:
            sessions_summary.append({
                "cash_session_id": str(s.public_id),
                "cash_register_name": s.cash_register.name,
                "opened_at": s.opened_at,
                "closed_at": s.closed_at,
                "expected_amount": str(s.closing_expected_amount or "0.00"),
                "counted_amount": str(s.closing_counted_amount or "0.00"),
                "difference": str(s.closing_diff_amount or "0.00"),
                "alert": "OK" if (s.closing_diff_amount or Decimal("0.00")) == Decimal("0.00") else "ALERTA_DIFF",
                "closed_by": getattr(s.closed_by, "username", None),
            })

        # Resumen por caja (movimientos del día)
        for reg in registers:
            movements = CashMovement.objects.filter(
                cash_register=reg,
                performed_at__gte=start_dt,
                performed_at__lte=end_dt,
            )
            operation_in = movements.filter(movement_type=CashMovement.MovementType.PAYMENT_IN).aggregate(s=Sum("amount"))["s"] or 0
            operation_out = movements.filter(movement_type=CashMovement.MovementType.LOAN_OUT).aggregate(s=Sum("amount"))["s"] or 0

            transfers_in = movements.filter(movement_type=CashMovement.MovementType.TRANSFER_IN).aggregate(s=Sum("amount"))["s"] or 0
            transfers_out = movements.filter(movement_type=CashMovement.MovementType.TRANSFER_OUT).aggregate(s=Sum("amount"))["s"] or 0

            adjustments_in = movements.filter(movement_type=CashMovement.MovementType.ADJUSTMENT_IN).aggregate(s=Sum("amount"))["s"] or 0
            adjustments_out = movements.filter(movement_type=CashMovement.MovementType.ADJUSTMENT_OUT).aggregate(s=Sum("amount"))["s"] or 0

            total_in = movements.filter(movement_type__endswith="_IN").aggregate(s=Sum("amount"))["s"] or 0
            total_out = movements.filter(movement_type__endswith="_OUT").aggregate(s=Sum("amount"))["s"] or 0
            alerts = []
            if Decimal(str(adjustments_out)) > Decimal("0"):
                alerts.append("ALERTA_FALTANTE")
            if Decimal(str(adjustments_in)) > Decimal("0"):
                alerts.append("ALERTA_SOBRANTE")


            # Última sesión cerrada del día para esa caja (si existe)
            last_closed = sessions.filter(cash_register=reg).order_by("-closed_at").first()

            registers_summary.append({
                "cash_register_id": str(reg.public_id),
                "cash_register_name": reg.name,
                "total_in": str(total_in),
                "total_out": str(total_out),
                "operation_in": str(operation_in),
                "operation_out": str(operation_out),
                "transfers_in": str(transfers_in),
                "transfers_out": str(transfers_out),
                "adjustments_in": str(adjustments_in),
                "adjustments_out": str(adjustments_out),
                "alerts": alerts,
                "last_closing": None if not last_closed else {
                    "cash_session_id": str(last_closed.public_id),
                    "expected_amount": str(last_closed.closing_expected_amount or "0.00"),
                    "counted_amount": str(last_closed.closing_counted_amount or "0.00"),
                    "difference": str(last_closed.closing_diff_amount or "0.00"),
                    "closed_at": last_closed.closed_at,
                }
                
            })

        # Transferencias del día (solo para esta sucursal)
        # Como tus transferencias están en CashMovement:
        # - TRANSFER_IN en la caja sucursal
        # - TRANSFER_OUT en caja origen (dueño u otra)
        # Aquí listamos las TRANSFER_IN de la sucursal (para no duplicar)
        transfers_in = CashMovement.objects.filter(
            branch=branch,
            movement_type=CashMovement.MovementType.TRANSFER_IN,
            performed_at__gte=start_dt,
            performed_at__lte=end_dt,
        ).select_related("cash_register", "performed_by")

        for t in transfers_in:
            transfers_summary.append({
                "performed_at": t.performed_at,
                "to_cash_register": t.cash_register.name,
                "amount": str(t.amount),
                "performed_by": getattr(t.performed_by, "username", None),
                "note": t.note,
            })

        return Response({
            "branch_code": branch.code,
            "branch_name": branch.name,
            "date": str(report_date),
            "range_start": start_dt,
            "range_end": end_dt,
            "registers": registers_summary,
            "sessions_closed": sessions_summary,
            "transfers_in": transfers_summary,
        }, status=200)
