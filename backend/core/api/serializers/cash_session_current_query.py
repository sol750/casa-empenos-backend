from rest_framework import serializers

class CashSessionCurrentQuerySerializer(serializers.Serializer):
    cash_register_id = serializers.UUIDField(required=False)
