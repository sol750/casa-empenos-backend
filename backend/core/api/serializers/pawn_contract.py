from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from core.api.serializers.pawn_item import PawnItemCreateSerializer


class PawnContractCreateSerializer(serializers.Serializer):
    cash_session_id = serializers.UUIDField()

    # ── Identificación del cliente ────────────────────────────────────────────
    # customer_ci: si el CI ya existe en BD, el nombre se rellena automáticamente
    # desde el registro del cliente (no hace falta enviarlo).
    # Si el CI no existe o se omite, customer_full_name pasa a ser obligatorio.
    customer_ci = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
        default="",
        help_text="Cédula de identidad. Si existe en BD, el nombre se auto-completa.",
    )
    customer_full_name = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
        #default="",
        help_text=(
            "Nombre completo. Obligatorio solo si el CI no existe en la base de datos. "
            "Si el cliente ya está registrado, se ignora (se usa el nombre del registro)."
        ),
    )

    # ── Capital ───────────────────────────────────────────────────────────────
    principal_amount = serializers.DecimalField(max_digits=12, decimal_places=2)

    # ── Fechas ────────────────────────────────────────────────────────────────
    # start_date actúa como effective_date para contratos históricos:
    # la vista lo usa como CashMovement.effective_date cuando is_legacy=True.
    # Para carga masiva envía la fecha exacta del libro físico (ej: "2024-03-15").
    start_date = serializers.DateField(required=False, allow_null=True, default=None)
    due_date   = serializers.DateField(required=False, allow_null=True, default=None)

    # ── Modo de interés ───────────────────────────────────────────────────────
    interest_mode = serializers.ChoiceField(
        choices=["FIXED", "PROMO"],
        required=False,
        default="FIXED",
    )
    promo_note = serializers.CharField(required=False, allow_blank=True, default="")

    # ── Fase de Sincronización ────────────────────────────────────────────────
    # Tasa libre: acepta cualquier valor (6%, 7.5%, 8%, etc.) para históricos.
    # Si se omite, el sistema aplica la tasa de categoría del cliente.
    interest_rate_monthly = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Tasa mensual explícita. Para contratos históricos usa la tasa real "
            "del libro. Si se omite, se calcula por categoría del cliente."
        ),
    )

    # Gastos adicionales del libro físico
    admin_fee = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        default=Decimal("0.00"),
        help_text="Gastos administrativos registrados en el libro físico.",
    )
    storage_fee = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        default=Decimal("0.00"),
        help_text="Gastos de almacenaje registrados en el libro físico.",
    )

    # Número de contrato del libro físico (ej: "Pt1-107")
    # Obligatorio para modo legado cuando el número debe coincidir con el libro.
    custom_contract_number = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
        default="",
        help_text="Número del contrato en el libro físico. Ej: Pt1-107",
    )

    # sync_operator_code: la vista lo sobreescribe con request.user.username,
    # pero puede enviarse manualmente si se prefiere otro valor.
    sync_operator_code = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        default="",
        help_text="Operador que digitalizó el contrato. Se auto-asigna al usuario autenticado.",
    )

    # ── Artículos empeñados ───────────────────────────────────────────────────
    items = PawnItemCreateSerializer(many=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Validaciones
    # ─────────────────────────────────────────────────────────────────────────

    def validate_principal_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El capital debe ser mayor a 0.")
        return value

    def validate(self, data):
        today      = timezone.now().date()
        start_date = data.get("start_date") or today

        # Fecha de inicio no puede ser futura
        if start_date > today:
            raise serializers.ValidationError(
                {"start_date": "La fecha de inicio no puede ser futura."}
            )

        # ── Lógica inteligente de cliente ─────────────────────────────────────
        # Si el CI existe en BD → el nombre se auto-completa en la vista,
        # así que no lo exigimos aquí.
        # Si el CI no existe o no se envía → el nombre es obligatorio para poder
        # registrar al cliente como texto libre en el contrato.
        customer_ci        = data.get("customer_ci", "").strip()
        customer_full_name = data.get("customer_full_name", "").strip()

        if customer_ci:
            from core.models import Customer
            ci_exists = Customer.objects.filter(ci=customer_ci).exists()
        else:
            ci_exists = False

        if not ci_exists and not customer_full_name:
            raise serializers.ValidationError(
                {
                    "customer_full_name": (
                        "El nombre del cliente es obligatorio cuando el CI "
                        "no está registrado en la base de datos."
                    )
                }
            )
        
        # IMPORTANTE: Aseguramos que los valores limpios vuelvan al diccionario data
        data["customer_ci"] = customer_ci
        data["customer_full_name"] = customer_full_name

        return data
