from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers


class PawnRenewalCreateSerializer(serializers.Serializer):
    pawn_contract_id = serializers.UUIDField()
    cash_session_id  = serializers.UUIDField()

    # ── Vencimiento ───────────────────────────────────────────────────────────
    # Opcional: si se omite, la vista calcula contract.due_date + 1 mes exacto
    # (mismo día del mes, "Fecha de Corte fija").
    # Para carga masiva puedes omitirlo siempre; para ajuste manual envíalo.
    new_due_date = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Nueva fecha de vencimiento. "
            "Si se omite, se calcula automáticamente como due_date actual + 1 mes."
        ),
    )

    fee_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=Decimal("0.00")
    )
    renew_date = serializers.DateField(required=False, allow_null=True, default=None)
    note       = serializers.CharField(required=False, allow_blank=True, default="")

    # ── Fase de Sincronización ────────────────────────────────────────────────
    # Controla dos cosas a la vez:
    #   1) Meses de interés a cobrar: desde interest_accrued_until hasta esta fecha
    #   2) CashMovement.effective_date: el ingreso impacta el saldo en esa fecha
    # Si se omite, se usa renew_date (o hoy). Esencial para carga histórica 2024-2025.
    effective_date = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Fecha real de la renovación según los libros físicos. "
            "Determina los meses de interés a cobrar y el saldo retroactivo de caja. "
            "Si se omite, se usa hoy."
        ),
    )

    def validate_fee_amount(self, value):
        # Convertir a Decimal antes de comparar para evitar TypeError con str
        if Decimal(str(value)) < Decimal("0"):
            raise serializers.ValidationError("La comisión no puede ser negativa.")
        return value

    def validate(self, data):
        today = timezone.now().date()

        eff = data.get("effective_date")
        if eff and eff > today:
            raise serializers.ValidationError(
                {"effective_date": "La fecha efectiva no puede ser futura."}
            )

        rd = data.get("renew_date")
        if rd and rd > today:
            raise serializers.ValidationError(
                {"renew_date": "La fecha de renovación no puede ser futura."}
            )

        # new_due_date: si se envía, validar que sea futura respecto a hoy
        # (la validación de que sea > contract.due_date ocurre en la vista,
        # donde ya tenemos el contrato cargado).
        nd = data.get("new_due_date")
        if nd and nd <= today:
            raise serializers.ValidationError(
                {"new_due_date": "La nueva fecha de vencimiento debe ser posterior a hoy."}
            )

        return data
