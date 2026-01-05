from rest_framework import serializers


class PawnPaymentCreateSerializer(serializers.Serializer):
    pawn_contract_id = serializers.UUIDField()
    cash_session_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_date = serializers.DateField(required=False)  # opcional (por defecto hoy)
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El pago debe ser mayor a 0.")
        return value
