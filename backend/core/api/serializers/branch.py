from rest_framework import serializers
from core.models import Branch

class BranchListSerializer(serializers.ModelSerializer):
    branch_id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Branch
        fields = ("branch_id", "name", "code", "address")

class BranchCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ("name", "code", "address")