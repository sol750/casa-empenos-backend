from rest_framework import serializers


class PawnRenewalCreateSerializer(serializers.Serializer):
    pawn_contract_id = serializers.UUIDField()
    cash_session_id = serializers.UUIDField()

    new_due_date = serializers.DateField()
    fee_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default="0.00")

    renew_date = serializers.DateField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_fee_amount(self, value):
        if value < 0:
            raise serializers.ValidationError("La comisión no puede ser negativa.")
        return value
