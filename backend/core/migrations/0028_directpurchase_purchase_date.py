"""
Migration 0028 — DirectPurchase.purchase_date

Añade el campo fecha real de adquisición para la Fase de Sincronización.
Permite registrar compras históricas con su fecha original de los libros.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_remove_max_principal"),
    ]

    operations = [
        migrations.AddField(
            model_name="directpurchase",
            name="purchase_date",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Fecha real de compra del artículo. Null = usar created_at.date().",
            ),
        ),
    ]
