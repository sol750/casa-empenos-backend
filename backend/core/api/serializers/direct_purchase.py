from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from core.models_inventory import DirectPurchase


class DirectPurchaseCreateSerializer(serializers.Serializer):
    cash_session_id = serializers.UUIDField()

    # ── Artículo ──────────────────────────────────────────────────────────────
    category = serializers.ChoiceField(
        choices=[c[0] for c in DirectPurchase.Category.choices],
        help_text="Categoría del artículo: LAPTOP, PHONE, JEWELRY, APPLIANCE, CONSOLE, INSTRUMENT, OTHER",
    )
    description = serializers.CharField(max_length=500)
    attributes  = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        default=dict,
        help_text="Atributos adicionales del artículo (marca, modelo, color, etc.).",
    )

    # ── Precios ───────────────────────────────────────────────────────────────
    purchase_price = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Monto pagado al vendedor. Genera movimiento PURCHASE_OUT en caja.",
    )
    market_value_estimate = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        required=False, allow_null=True, default=None,
        help_text="Valor de mercado estimado (base del cálculo MVI 75%).",
    )
    estimated_selling_price = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        required=False, allow_null=True, default=None,
        help_text=(
            "PVP tentativo. Si se envía: status=EN_VENTA, pvp=este valor, "
            "projected_profit=pvp-purchase_price. "
            "Si se omite: status=COMPRADO_PENDIENTE (el dueño fija el precio después)."
        ),
    )

    # ── Fechas ────────────────────────────────────────────────────────────────
    # purchase_date / effective_date son sinónimos; se acepta cualquiera de los dos.
    # Actúa como DirectPurchase.purchase_date y CashMovement.effective_date para
    # que el saldo histórico de caja sea correcto en la carga masiva.
    purchase_date = serializers.DateField(
        required=False, allow_null=True, default=None,
        help_text="Fecha real de compra (YYYY-MM-DD). Para carga histórica.",
    )
    effective_date = serializers.DateField(
        required=False, allow_null=True, default=None,
        help_text="Alias de purchase_date. Si se envían ambos, purchase_date tiene prioridad.",
    )

    # ── Vendedor (sin FK en el modelo; se registra en attributes) ────────────
    customer_ci = serializers.CharField(
        max_length=30, required=False, allow_blank=True, default="",
        help_text="CI del vendedor. Si existe en BD se auto-vincula al registro de clientes.",
    )
    customer_full_name = serializers.CharField(
        max_length=120, required=False, allow_blank=True,
        help_text=(
            "Nombre completo del vendedor. Obligatorio si el CI no está en la base de datos "
            "y se desea crear un registro de cliente (placeholder)."
        ),
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Validaciones
    # ─────────────────────────────────────────────────────────────────────────

    def validate_purchase_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("El precio de compra debe ser mayor a 0.")
        return value

    def validate_estimated_selling_price(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("El precio de venta estimado debe ser mayor a 0.")
        return value

    def validate_market_value_estimate(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("El valor de mercado estimado debe ser mayor a 0.")
        return value

    def validate(self, data):
        today = timezone.now().date()

        # Normalizar la fecha efectiva: purchase_date tiene prioridad sobre effective_date
        eff = data.get("purchase_date") or data.get("effective_date")
        if eff:
            if eff > today:
                raise serializers.ValidationError(
                    {"purchase_date": "La fecha de compra no puede ser futura."}
                )
        # Guardar la fecha resuelta en un solo campo para que la vista lo consuma fácilmente
        data["_resolved_date"] = eff  # None si no se envió ninguna

        # Normalizar strings del vendedor
        data["customer_ci"]        = data.get("customer_ci", "").strip()
        data["customer_full_name"] = data.get("customer_full_name", "").strip()

        # Validar que estimated_selling_price >= purchase_price (advertencia preventiva)
        esp = data.get("estimated_selling_price")
        pp  = data.get("purchase_price")
        if esp is not None and pp is not None and esp < pp:
            raise serializers.ValidationError(
                {
                    "estimated_selling_price": (
                        "El precio de venta estimado no puede ser menor al precio de compra."
                    )
                }
            )

        return data
