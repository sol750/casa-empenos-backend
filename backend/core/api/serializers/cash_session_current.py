from rest_framework import serializers
from core.models import CashSession


class CashSessionCurrentSerializer(serializers.ModelSerializer):
    cash_session_id = serializers.UUIDField(source="public_id")
    cash_register_name = serializers.CharField(source="cash_register.name")
    branch_code = serializers.CharField(source="branch.code", allow_null=True)

    class Meta:
        model = CashSession
        fields = (
            "cash_session_id",
            "cash_register_name",
            "branch_code",
            "opening_amount",
            "opened_at",
            "status",
        )