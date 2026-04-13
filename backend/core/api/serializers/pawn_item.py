from rest_framework import serializers


class PawnItemCreateSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=[
        "LAPTOP", "PHONE", "JEWELRY", "APPLIANCE",
        "CONSOLE", "INSTRUMENT", "OTHER"
    ])

    description = serializers.CharField(required=False, allow_blank=True)

    attributes = serializers.JSONField(required=False)

    has_box = serializers.BooleanField(required=False, default=False)
    has_charger = serializers.BooleanField(required=False, default=False)

    condition = serializers.ChoiceField(
        choices=["EXCELLENT", "GOOD", "WORN", "DAMAGED"],
        required=False,
        default="GOOD",
    )

    observations = serializers.CharField(required=False, allow_blank=True, default="")

    # Monto prestado por este artículo (opcional, para desglose multi-artículo)
    loan_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        required=False, allow_null=True, default=None,
    )