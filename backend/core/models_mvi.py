"""
Módulo de Valoración Inteligente (MVI).
Previene sobre-tasación o sub-tasación por cajeros inexpertos.
"""
import uuid
from django.conf import settings
from django.db import models
from decimal import Decimal


class MVIConfig(models.Model):
    """
    Configuración global del MVI. Singleton (pk=1).
    El dueño actualiza estos valores desde su panel.
    """
    # ── Metales preciosos ─────────────────────────────────────────────────────
    gold_price_24k_gram_bs  = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("580.00"),
                                                   help_text="Precio del gramo de oro 24k en Bs (actualizar diariamente)")
    silver_price_gram_bs    = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("7.50"),
                                                   help_text="Precio del gramo de plata en Bs")

    # ── Depreciación por categoría (% mensual) ────────────────────────────────
    depreciation_phone_pct      = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("4.50"),
                                                       help_text="Celulares: % depreciación mensual")
    depreciation_laptop_pct     = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("3.50"),
                                                       help_text="Laptops: % depreciación mensual")
    depreciation_console_pct    = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("2.50"),
                                                       help_text="Consolas: % depreciación mensual")
    depreciation_appliance_pct  = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.50"),
                                                       help_text="Electrodomésticos: % depreciación mensual")
    depreciation_other_pct      = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("2.00"),
                                                       help_text="Otros: % depreciación mensual")

    # ── Relación Préstamo/Valor (Loan-to-Value) ───────────────────────────────
    loan_to_value_pct           = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("60.00"),
                                                       help_text="Máximo a prestar como % del valor estimado (ej: 60%)")
    vip_bonus_pct               = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("15.00"),
                                                       help_text="% extra permitido para clientes ORO sobre la recomendación")

    # ── Control de sobre-tasación ─────────────────────────────────────────────
    soft_warning_pct            = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("15.00"),
                                                       help_text="% sobre el máximo recomendado que genera advertencia")
    hard_block_pct              = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("30.00"),
                                                       help_text="% sobre el máximo recomendado que bloquea y requiere autorización del dueño")

    updated_at  = models.DateTimeField(auto_now=True)
    updated_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="mvi_config_updates")

    class Meta:
        verbose_name = "Configuración MVI"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"MVI Config | Oro 24k: {self.gold_price_24k_gram_bs} Bs/g"


class AppraisalOverride(models.Model):
    """
    Solicitud de autorización cuando un cajero quiere prestar más
    de lo que el MVI recomienda (supera el hard_block_pct).
    El dueño aprueba o rechaza desde su panel.
    """
    class Status(models.TextChoices):
        PENDING  = "PENDING",  "Pendiente"
        APPROVED = "APPROVED", "Aprobado"
        DENIED   = "DENIED",   "Rechazado"

    public_id           = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    contract            = models.OneToOneField("PawnContract", on_delete=models.CASCADE,
                                               null=True, blank=True,
                                               related_name="appraisal_override",
                                               help_text="Contrato creado tras la autorización (null mientras está pendiente)")

    # Datos de la tasación
    branch              = models.ForeignKey("Branch", on_delete=models.PROTECT)
    category            = models.CharField(max_length=20)
    description         = models.TextField()
    condition           = models.CharField(max_length=20, default="GOOD")
    customer_ci         = models.CharField(max_length=30, blank=True)

    system_recommendation   = models.DecimalField(max_digits=12, decimal_places=2)
    system_max_allowed      = models.DecimalField(max_digits=12, decimal_places=2,
                                                   help_text="Máximo antes del bloqueo duro")
    principal_requested     = models.DecimalField(max_digits=12, decimal_places=2)
    override_reason         = models.TextField()

    # Auditoría
    requested_by        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                            related_name="appraisal_overrides_requested")
    requested_at        = models.DateTimeField(auto_now_add=True)
    authorized_by       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                            null=True, blank=True,
                                            related_name="appraisal_overrides_authorized")
    authorized_at       = models.DateTimeField(null=True, blank=True)
    authorization_note  = models.TextField(blank=True)
    status              = models.CharField(max_length=20, choices=Status.choices,
                                           default=Status.PENDING)

    class Meta:
        verbose_name = "Autorización de Sobre-Tasación"
        verbose_name_plural = "Autorizaciones de Sobre-Tasación"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Override {self.category} {self.principal_requested} Bs | {self.status}"
