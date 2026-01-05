from rest_framework import serializers


class CashSessionOpenSerializer(serializers.Serializer):
    cash_register_id = serializers.UUIDField()
    opening_amount = serializers.DecimalField(max_digits=12, decimal_places=2)

    def validate_opening_amount(self, value):
        if value < 0:
            raise serializers.ValidationError("El monto inicial no puede ser negativo.")
        return value
