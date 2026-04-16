from rest_framework import serializers
from core.models import CashRegister, Branch

class CashRegisterCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60)
    register_type = serializers.ChoiceField(choices=CashRegister.RegisterType.choices)
    branch_id = serializers.UUIDField(required=False)

    def validate(self, data):
        if data["register_type"] == "BRANCH" and not data.get("branch_id"):
            raise serializers.ValidationError("branch_id es requerido para cajas de sucursal.")
        return data
class CashRegisterListSerializer(serializers.ModelSerializer):
    cash_register_id = serializers.UUIDField(source="public_id")
    branch_code = serializers.CharField(source="branch.code", allow_null=True)
    branch_name = serializers.CharField(source="branch.name", allow_null=True)
    assigned_employee = serializers.SerializerMethodField()

    class Meta:
        model = CashRegister
        fields = (
            "cash_register_id", "name", "register_type",
            "branch_code", "branch_name",
            "assigned_employee",
        )

    def get_assigned_employee(self, obj):
        """Empleado activo asignado a esta caja (si existe)."""
        try:
            emp = obj.assigned_employees.filter(
                status__in=("ACTIVE", "ON_VACATION")
            ).select_related("user").first()
            if emp:
                return {
                    "employee_id": str(emp.public_id),
                    "ci":          emp.ci,
                    "full_name":   emp.full_name,
                    "status":      emp.status,
                }
        except Exception:
            pass
        return None
