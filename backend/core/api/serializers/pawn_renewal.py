from rest_framework import serializers
from django.utils import timezone


class PawnRenewalCreateSerializer(serializers.Serializer):
    pawn_contract_id = serializers.UUIDField()
    cash_session_id  = serializers.UUIDField()

    new_due_date = serializers.DateField()
    fee_amount   = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default="0.00"
    )
    renew_date   = serializers.DateField(required=False)
    note         = serializers.CharField(required=False, allow_blank=True, default="")

    # ── Fase de Sincronización ────────────────────────────────────────────────
    # Si se envía, reemplaza renew_date como fecha base para:
    #   1) Calcular meses de interés acumulado (fixed_interest_for_period)
    #   2) CashMovement.effective_date (impacto retroactivo en caja)
    effective_date = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Fecha real de la renovación según los libros físicos. "
            "Determina los meses de interés a cobrar. Si se omite, se usa hoy."
        ),
    )

    def validate_fee_amount(self, value):
        if value < 0:
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
        return data
