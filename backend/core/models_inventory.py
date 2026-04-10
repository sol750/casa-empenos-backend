"""
Módulo de Inventario: Compras Directas (CD) y Vitrina.
Ciclo: COMPRADO_PENDIENTE → EN_VENTA → VENDIDO
"""
import uuid
from django.conf import settings
from django.db import models


class DirectPurchase(models.Model):
    """
    Artículo adquirido directamente por la casa de empeños (Compra Directa - CD).
    El dueño del artículo pasa a ser la casa, a diferencia del empeño.
    """
    class Status(models.TextChoices):
        COMPRADO_PENDIENTE = "COMPRADO_PENDIENTE", "Comprado – Pendiente de precio"
        EN_VENTA           = "EN_VENTA",           "En Vitrina"
        VENDIDO            = "VENDIDO",            "Vendido"
        CANCELADO          = "CANCELADO",          "Cancelado"

    class Category(models.TextChoices):
        LAPTOP     = "LAPTOP",     "Laptop"
        PHONE      = "PHONE",      "Celular"
        JEWELRY    = "JEWELRY",    "Joya"
        APPLIANCE  = "APPLIANCE",  "Electrodoméstico"
        CONSOLE    = "CONSOLE",    "Consola"
        INSTRUMENT = "INSTRUMENT", "Instrumento musical"
        OTHER      = "OTHER",      "Otro"

    public_id  = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    branch     = models.ForeignKey("core.Branch",      on_delete=models.PROTECT, related_name="direct_purchases")
    status     = models.CharField(max_length=30, choices=Status.choices, default=Status.COMPRADO_PENDIENTE)

    # ── Fase A: Adquisición (Cajero) ────────────────────────────────────────
    cash_session        = models.ForeignKey("core.CashSession", on_delete=models.PROTECT, related_name="direct_purchases")
    created_by          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="direct_purchases_created")
    created_at          = models.DateTimeField(auto_now_add=True)

    category            = models.CharField(max_length=20, choices=Category.choices)
    description         = models.TextField()
    attributes          = models.JSONField(default=dict, blank=True)

    market_value_estimate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                                help_text="Estimado del valor de mercado (base para calcular oferta MVI)")
    purchase_price      = models.DecimalField(max_digits=12, decimal_places=2,
                                              help_text="Monto pagado al vendedor (CD – salida de caja)")

    # ── Fase B: Valoración y Precio (Dueño) ────────────────────────────────
    pvp                 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                              help_text="Precio de vitrina asignado por el dueño")
    projected_profit    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    priced_by           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                            null=True, blank=True, related_name="direct_purchases_priced")
    priced_at           = models.DateTimeField(null=True, blank=True)
    qr_code_data        = models.CharField(max_length=255, null=True, blank=True,
                                           help_text="UUID del artículo codificado en el QR")

    # ── Fase C: Venta (Cajero) ──────────────────────────────────────────────
    sale_cash_session   = models.ForeignKey("core.CashSession", on_delete=models.PROTECT,
                                            null=True, blank=True, related_name="direct_sales")
    sold_by             = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                            null=True, blank=True, related_name="direct_purchases_sold")
    sold_at             = models.DateTimeField(null=True, blank=True)
    sale_price          = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_profit       = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                              help_text="UV = Precio venta - Costo CD")

    class Meta:
        verbose_name = "Compra Directa"
        verbose_name_plural = "Compras Directas"
        ordering = ["-created_at"]

    def __str__(self):
        return f"CD-{str(self.public_id)[:8]} | {self.category} | {self.status}"

    @property
    def suggested_mvi(self):
        """Oferta sugerida al vendedor: 75% del valor de mercado estimado."""
        if self.market_value_estimate:
            return (self.market_value_estimate * 75 / 100).quantize(__import__("decimal").Decimal("0.01"))
        return None


class DirectPurchasePhoto(models.Model):
    """Fotos del artículo comprado. Mínimo 3 requeridas antes de pasar a EN_VENTA."""
    public_id   = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    purchase    = models.ForeignKey(DirectPurchase, on_delete=models.CASCADE, related_name="photos")
    photo       = models.FileField(upload_to="inventory/photos/%Y/%m/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inventory_photos")

    class Meta:
        verbose_name = "Foto de artículo"
        verbose_name_plural = "Fotos de artículos"
