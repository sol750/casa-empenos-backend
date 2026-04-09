from decimal import Decimal
from rest_framework import serializers


class InvestorCreateSerializer(serializers.Serializer):
    full_name       = serializers.CharField(max_length=255)
    ci              = serializers.CharField(required=False, allow_blank=True, default="")
    profit_rate_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2,
        min_value=Decimal("0.00"), max_value=Decimal("100.00"),
        required=False, default=Decimal("50.00"),
    )