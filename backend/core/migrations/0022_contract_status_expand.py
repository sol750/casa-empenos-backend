"""
0022 – Expansión de estados de PawnContract
=============================================
Agrega CANCELLED, EN_VENTA y SOLD a PawnContract.Status.
No modifica estructura de columna (CharField sin CHECK constraint en PostgreSQL).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_aguinaldo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pawncontract",
            name="status",
            field=models.CharField(
                choices=[
                    ("ACTIVE",    "Activo"),
                    ("CLOSED",    "Cerrado"),
                    ("DEFAULTED", "En mora"),
                    ("CANCELLED", "Cancelado"),
                    ("EN_VENTA",  "En Vitrina"),
                    ("SOLD",      "Vendido"),
                ],
                default="ACTIVE",
                max_length=20,
            ),
        ),
    ]
