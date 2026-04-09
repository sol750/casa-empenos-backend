from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.models_security import Role, UserRole, UserBranchAccess
from core.models import Branch

User = get_user_model()


class UserListSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="id", read_only=True)
    roles = serializers.SerializerMethodField()
    branches = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("user_id", "username", "is_active", "roles", "branches")

    def get_roles(self, obj):
        return list(
            UserRole.objects.filter(user=obj).values_list("role__code", flat=True)
        )

    def get_branches(self, obj):
        return list(
            UserBranchAccess.objects.filter(user=obj).values_list("branch__code", flat=True)
        )


class UserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=6)
    is_active = serializers.BooleanField(required=False, default=True)
    roles = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False
    )
    branches = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
        required=False,
        default=list
    )


class UserUpdateSerializer(serializers.Serializer):
    is_active = serializers.BooleanField(required=False)
    roles = serializers.ListField(child=serializers.CharField(), required=False)
    branches = serializers.ListField(child=serializers.CharField(), required=False)
    password = serializers.CharField(write_only=True, required=False, min_length=6)
