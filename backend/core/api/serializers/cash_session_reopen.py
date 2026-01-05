from rest_framework import serializers


class CashSessionReopenSerializer(serializers.Serializer):
    cash_session_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=255)
