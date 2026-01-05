from rest_framework import serializers


class DailySummaryQuerySerializer(serializers.Serializer):
    branch_code = serializers.CharField(max_length=20)
    date = serializers.DateField(required=False)  # si no viene, usamos hoy
