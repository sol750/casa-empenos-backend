"""
0019 – Módulo de Mora Automática
=================================
Cambios:
  - Branch: añade grace_period_days (default 30)
  - PawnContract: añade defaulted_at (DateTimeField, nullable)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_cashflow_enhancements"),
    ]

    operations = [
        # ── Branch: período de gracia ─────────────────────────────────────────
        migrations.AddField(
            model_name="branch",
            name="grace_period_days",
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text="Días hábiles de gracia tras el vencimiento antes de pasar a mora.",
            ),
        ),
        # ── PawnContract: fecha/hora de mora ──────────────────────────────────
        migrations.AddField(
            model_name="pawncontract",
            name="defaulted_at",
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text="Fecha/hora en que el contrato fue marcado automáticamente como DEFAULTED.",
            ),
        ),
    ]
