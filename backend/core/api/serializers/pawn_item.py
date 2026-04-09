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

    # ✅ IGUAL QUE EL MODELO
    observations = serializers.CharField(required=False, allow_blank=True, default="")