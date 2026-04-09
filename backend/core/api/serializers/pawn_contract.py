from rest_framework import serializers
from django.utils import timezone
from core.api.serializers.pawn_item import PawnItemCreateSerializer


class PawnContractCreateSerializer(serializers.Serializer):
    cash_session_id = serializers.UUIDField()

    customer_full_name = serializers.CharField(max_length=120)
    customer_ci = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")

    principal_amount = serializers.DecimalField(max_digits=12, decimal_places=2)

    start_date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False)

    interest_mode = serializers.ChoiceField(
        choices=["MONTHLY_PRORATED", "FIXED", "PROMO"],
        required=False,
        default="MONTHLY_PRORATED",
    )

    promo_note = serializers.CharField(required=False, allow_blank=True, default="")
    

    # ✅ ITEMS
    items = PawnItemCreateSerializer(many=True)

    def validate_principal_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El capital debe ser mayor a 0.")
        return value

    def validate(self, data):
        start_date = data.get("start_date", timezone.now().date())
        today = timezone.now().date()

        if start_date > today:
            raise serializers.ValidationError(
                {"start_date": "La fecha de inicio no puede ser futura."}
            )

        return data