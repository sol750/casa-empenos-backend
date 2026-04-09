from rest_framework import serializers

class InvestorCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField()
    ci = serializers.CharField(required=False, allow_blank=True)