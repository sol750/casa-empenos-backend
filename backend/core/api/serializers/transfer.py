from rest_framework import serializers

class TransferCreateSerializer(serializers.Serializer):
    from_cash_register_id = serializers.UUIDField()
    to_cash_register_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    note = serializers.CharField(required=False, allow_blank=True)