"""
Migración 0025
==============
- Añade InterestCategoryConfig (tasas por categoría configurables en BD)
- Añade Customer.custom_rate_pct (tasa mensual individual por cliente)
- Añade PawnItem.loan_amount (capital prestado por artículo)
"""
from decimal import Decimal
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0024_mvi_condition"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── 1. InterestCategoryConfig ─────────────────────────────────────────
        migrations.CreateModel(
            name="InterestCategoryConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(
                    choices=[("BRONCE", "Bronce"), ("PLATA", "Plata"), ("ORO", "Oro")],
                    max_length=10,
                    unique=True,
                )),
                ("base_rate_pct", models.DecimalField(
                    decimal_places=2,
                    max_digits=6,
                    help_text="Tasa mensual base (%) para esta categoría",
                )),
                ("max_principal", models.DecimalField(
                    decimal_places=2,
                    max_digits=12,
                    help_text="Capital máximo prestable para esta categoría (Bs.)",
                )),
                ("updated_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="interest_configs_updated",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Configuración de Tasa por Categoría",
                "verbose_name_plural": "Configuraciones de Tasas",
            },
        ),

        # ── 2. Customer.custom_rate_pct ───────────────────────────────────────
        migrations.AddField(
            model_name="customer",
            name="custom_rate_pct",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=6,
                null=True,
                help_text="Tasa mensual personalizada. Vacío = usar política de categoría.",
            ),
        ),

        # ── 3. PawnItem.loan_amount ───────────────────────────────────────────
        migrations.AddField(
            model_name="pawnitem",
            name="loan_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=12,
                null=True,
                help_text="Capital prestado atribuido a este artículo específico",
            ),
        ),
    ]
