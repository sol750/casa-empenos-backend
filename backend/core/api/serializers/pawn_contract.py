from decimal import Decimal
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
        choices=["FIXED", "PROMO"],
        required=False,
        default="FIXED",
    )
    promo_note = serializers.CharField(required=False, allow_blank=True, default="")

    # ── Campos de Fase de Sincronización (contratos históricos 2023-2025) ────
    # Tasa libre: en modo legado se acepta cualquier valor (6%, 7.5%, 8%, etc.)
    interest_rate_monthly = serializers.DecimalField(
        max_digits=6, decimal_places=2,
        required=False, allow_null=True, default=None,
        help_text="Solo para modo legado. Si se omite, el sistema aplica la tasa de categoría.",
    )
    # Gastos adicionales registrados en los libros físicos
    admin_fee = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, default=Decimal("0.00"),
        help_text="Gastos administrativos cobrados al momento del contrato.",
    )
    storage_fee = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, default=Decimal("0.00"),
        help_text="Gastos de almacenaje cobrados al momento del contrato.",
    )
    # Número de contrato personalizado (ej: Pt1-107 del libro físico)
    custom_contract_number = serializers.CharField(
        max_length=30, required=False, allow_blank=True, default="",
        help_text="Número del contrato en el libro físico. Ej: Pt1-107",
    )
    # Código de la sucursal/operador que está digitalizando
    sync_operator_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, default="",
        help_text="Iniciales de la sucursal que digitaliza. Ej: Pt1",
    )

    # ── ITEMS ─────────────────────────────────────────────────────────────────
    items = PawnItemCreateSerializer(many=True)

    def validate_principal_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El capital debe ser mayor a 0.")
        return value

    def validate(self, data):
        start_date = data.get("start_date", timezone.now().date())
        today = timezone.now().date()

        # Fecha futura siempre es inválida (no tiene sentido predar mañana)
        if start_date > today:
            raise serializers.ValidationError(
                {"start_date": "La fecha de inicio no puede ser futura."}
            )

        return data