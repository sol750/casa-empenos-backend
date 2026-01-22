from rest_framework import serializers
from core.models import CashMovement


class CashMovementListSerializer(serializers.ModelSerializer):
    cash_movement_id = serializers.UUIDField(source="public_id")
    cash_session_id = serializers.UUIDField(source="cash_session.public_id")
    cash_register_id = serializers.UUIDField(source="cash_register.public_id")
    branch_code = serializers.CharField(source="branch.code", allow_null=True)
    performed_by = serializers.CharField(source="performed_by.username")

    class Meta:
        model = CashMovement
        fields = (
            "cash_movement_id",
            "cash_session_id",
            "cash_register_id",
            "branch_code",
            "movement_type",
            "amount",
            "note",
            "performed_by",
            "performed_at",
        )
