from rest_framework import serializers


class MeSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField())
    branches = serializers.ListField(child=serializers.CharField())
