from rest_framework import serializers


class CashSessionCloseSerializer(serializers.Serializer):
    cash_session_id = serializers.UUIDField()
    counted_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_counted_amount(self, value):
        if value < 0:
            raise serializers.ValidationError("El monto contado no puede ser negativo.")
        return value