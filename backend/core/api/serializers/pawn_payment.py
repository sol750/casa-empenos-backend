from rest_framework import serializers
from django.utils import timezone


class PawnPaymentCreateSerializer(serializers.Serializer):
    pawn_contract_id = serializers.UUIDField()
    cash_session_id  = serializers.UUIDField()
    amount           = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_date     = serializers.DateField(required=False)
    note             = serializers.CharField(required=False, allow_blank=True, default="")

    # ── Fase de Sincronización ────────────────────────────────────────────────
    # Si se envía, se usa para:
    #   1) Calcular meses de interés acumulado (fixed_interest_for_period)
    #   2) CashMovement.effective_date (impacto retroactivo en caja)
    # Si se omite, se comporta igual que payment_date (o hoy).
    effective_date = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Fecha real del pago según los libros físicos. "
            "Controla el meses de interés y el saldo histórico de caja."
        ),
    )

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El pago debe ser mayor a 0.")
        return value

    def validate(self, data):
        today = timezone.now().date()
        eff = data.get("effective_date")
        if eff and eff > today:
            raise serializers.ValidationError(
                {"effective_date": "La fecha efectiva no puede ser futura."}
            )
        pd = data.get("payment_date")
        if pd and pd > today:
            raise serializers.ValidationError(
                {"payment_date": "La fecha de pago no puede ser futura."}
            )
        return data
