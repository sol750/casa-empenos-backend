from rest_framework import serializers
from core.models import CashRegister


class CashRegisterListSerializer(serializers.ModelSerializer):
    cash_register_id = serializers.UUIDField(source="public_id")
    branch_code = serializers.CharField(source="branch.code", allow_null=True)
    branch_name = serializers.CharField(source="branch.name", allow_null=True)

    class Meta:
        model = CashRegister
        fields = ("cash_register_id", "name", "register_type", "branch_code", "branch_name")
