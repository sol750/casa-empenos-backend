"""
Migration 0024: MVI module + PawnItem.condition
- MVIConfig (singleton)
- AppraisalOverride
- PawnItem.condition field
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0023_amortization_inventory"),
    ]

    operations = [
        # ── MVIConfig ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="MVIConfig",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("gold_price_24k_gram_bs",     models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("580.00"))),
                ("silver_price_gram_bs",        models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("7.50"))),
                ("depreciation_phone_pct",      models.DecimalField(max_digits=5,  decimal_places=2, default=Decimal("4.50"))),
                ("depreciation_laptop_pct",     models.DecimalField(max_digits=5,  decimal_places=2, default=Decimal("3.50"))),
                ("depreciation_console_pct",    models.DecimalField(max_digits=5,  decimal_places=2, default=Decimal("2.50"))),
                ("depreciation_appliance_pct",  models.DecimalField(max_digits=5,  decimal_places=2, default=Decimal("1.50"))),
                ("depreciation_other_pct",      models.DecimalField(max_digits=5,  decimal_places=2, default=Decimal("2.00"))),
                ("loan_to_value_pct",           models.DecimalField(max_digits=5,  decimal_places=2, default=Decimal("60.00"))),
                ("vip_bonus_pct",               models.DecimalField(max_digits=5,  decimal_places=2, default=Decimal("15.00"))),
                ("soft_warning_pct",            models.DecimalField(max_digits=5,  decimal_places=2, default=Decimal("15.00"))),
                ("hard_block_pct",              models.DecimalField(max_digits=5,  decimal_places=2, default=Decimal("30.00"))),
                ("updated_at",  models.DateTimeField(auto_now=True)),
                ("updated_by",  models.ForeignKey(
                    settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.SET_NULL,
                    null=True, blank=True, related_name="mvi_config_updates"
                )),
            ],
            options={"verbose_name": "Configuración MVI"},
        ),

        # ── AppraisalOverride ─────────────────────────────────────────────────
        migrations.CreateModel(
            name="AppraisalOverride",
            fields=[
                ("id",          models.AutoField(primary_key=True, serialize=False)),
                ("public_id",   models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
                ("contract",    models.OneToOneField(
                    "core.PawnContract", on_delete=django.db.models.deletion.CASCADE,
                    null=True, blank=True, related_name="appraisal_override"
                )),
                ("branch",      models.ForeignKey("core.Branch", on_delete=django.db.models.deletion.PROTECT)),
                ("category",    models.CharField(max_length=20)),
                ("description", models.TextField()),
                ("condition",   models.CharField(max_length=20, default="GOOD")),
                ("customer_ci", models.CharField(max_length=30, blank=True)),
                ("system_recommendation",   models.DecimalField(max_digits=12, decimal_places=2)),
                ("system_max_allowed",      models.DecimalField(max_digits=12, decimal_places=2)),
                ("principal_requested",     models.DecimalField(max_digits=12, decimal_places=2)),
                ("override_reason",         models.TextField()),
                ("requested_by",    models.ForeignKey(
                    settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                    related_name="appraisal_overrides_requested"
                )),
                ("requested_at",    models.DateTimeField(auto_now_add=True)),
                ("authorized_by",   models.ForeignKey(
                    settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True, related_name="appraisal_overrides_authorized"
                )),
                ("authorized_at",       models.DateTimeField(null=True, blank=True)),
                ("authorization_note",  models.TextField(blank=True)),
                ("status",  models.CharField(
                    max_length=20,
                    choices=[("PENDING", "Pendiente"), ("APPROVED", "Aprobado"), ("DENIED", "Rechazado")],
                    default="PENDING"
                )),
            ],
            options={
                "verbose_name": "Autorización de Sobre-Tasación",
                "verbose_name_plural": "Autorizaciones de Sobre-Tasación",
                "ordering": ["-requested_at"],
            },
        ),

        # ── PawnItem.condition ────────────────────────────────────────────────
        migrations.AddField(
            model_name="pawnitem",
            name="condition",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("EXCELLENT", "Excelente"),
                    ("GOOD",      "Bueno"),
                    ("WORN",      "Desgastado"),
                    ("DAMAGED",   "Dañado"),
                ],
                default="GOOD",
            ),
        ),
    ]
