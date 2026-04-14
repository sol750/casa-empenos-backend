"""
Migration 0026 — Fase de Sincronización

Cambios:
  • PawnContract: +admin_fee, +storage_fee, +sync_operator_code
  • CashMovement: +effective_date
  • New model: LegacyBalanceAdjustment
"""
from decimal import Decimal
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_interest_config_customer_rate_pawnitem_loanamount"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── PawnContract: gastos adicionales ────────────────────────────────
        migrations.AddField(
            model_name="pawncontract",
            name="admin_fee",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Gastos administrativos cobrados al momento de crear el contrato.",
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name="pawncontract",
            name="storage_fee",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Gastos de almacenaje cobrados al momento de crear el contrato.",
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name="pawncontract",
            name="sync_operator_code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Iniciales de la sucursal que digitalizó este contrato. Ej: Pt1",
                max_length=20,
            ),
        ),

        # ── CashMovement: fecha efectiva para caja retroactiva ───────────────
        migrations.AddField(
            model_name="cashmovement",
            name="effective_date",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Fecha real del documento físico. Solo se usa en modo sincronización legado.",
            ),
        ),

        # ── LegacyBalanceAdjustment ──────────────────────────────────────────
        migrations.CreateModel(
            name="LegacyBalanceAdjustment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="legacy_adjustments",
                        to="core.branch",
                    ),
                ),
                ("adjustment_date", models.DateField(
                    help_text="Fecha del libro físico que se está ajustando (ej: último día del mes).",
                )),
                ("book_balance", models.DecimalField(
                    decimal_places=2,
                    max_digits=12,
                    help_text="Saldo físico según el libro a esta fecha (Bs.).",
                )),
                ("note", models.TextField(blank=True, default="")),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="legacy_adjustments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Ajuste de Saldo Legado",
                "verbose_name_plural": "Ajustes de Saldo Legado",
                "ordering": ["branch", "adjustment_date"],
                "unique_together": {("branch", "adjustment_date")},
            },
        ),
    ]
