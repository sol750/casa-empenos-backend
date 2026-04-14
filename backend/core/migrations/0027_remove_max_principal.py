"""
Migration 0027 — Eliminar límites automáticos de crédito

Cambios:
  • InterestCategoryConfig: elimina campo max_principal
    (El monto lo decide el dueño manualmente. Sin restricción automática.)
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_sync_phase"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="interestcategoryconfig",
            name="max_principal",
        ),
    ]
