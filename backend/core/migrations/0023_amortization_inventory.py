"""
0023 – Amortizaciones e Inventario (Compra Directa)
=====================================================
- PawnAmortization: adenda de amortización de contrato
- DirectPurchase: artículo comprado directamente (CD)
- DirectPurchasePhoto: fotos del artículo (mín. 3 para pasar a vitrina)
"""
import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_contract_status_expand"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── PawnAmortization ──────────────────────────────────────────────
        migrations.CreateModel(
            name="PawnAmortization",
            fields=[
                ("id",               models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("public_id",        models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("performed_at",     models.DateTimeField(auto_now_add=True)),
                ("outstanding_before", models.DecimalField(decimal_places=2, max_digits=12)),
                ("capital_paid",     models.DecimalField(decimal_places=2, max_digits=12)),
                ("interest_paid",    models.DecimalField(decimal_places=2, max_digits=12)),
                ("previous_due_date", models.DateField()),
                ("new_due_date",     models.DateField()),
                ("note",             models.CharField(blank=True, default="", max_length=255)),
                ("contract",         models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                       related_name="amortizations", to="core.pawncontract")),
                ("cash_session",     models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                       related_name="amortizations", to="core.cashsession")),
                ("performed_by",     models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                       related_name="amortizations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Amortización", "verbose_name_plural": "Amortizaciones"},
        ),

        # ── DirectPurchase ────────────────────────────────────────────────
        migrations.CreateModel(
            name="DirectPurchase",
            fields=[
                ("id",                     models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("public_id",              models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("status",                 models.CharField(
                    choices=[
                        ("COMPRADO_PENDIENTE", "Comprado – Pendiente de precio"),
                        ("EN_VENTA",           "En Vitrina"),
                        ("VENDIDO",            "Vendido"),
                        ("CANCELADO",          "Cancelado"),
                    ],
                    default="COMPRADO_PENDIENTE", max_length=30,
                )),
                ("created_at",             models.DateTimeField(auto_now_add=True)),
                ("category",               models.CharField(
                    choices=[
                        ("LAPTOP", "Laptop"), ("PHONE", "Celular"), ("JEWELRY", "Joya"),
                        ("APPLIANCE", "Electrodoméstico"), ("CONSOLE", "Consola"),
                        ("INSTRUMENT", "Instrumento musical"), ("OTHER", "Otro"),
                    ],
                    max_length=20,
                )),
                ("description",            models.TextField()),
                ("attributes",             models.JSONField(blank=True, default=dict)),
                ("market_value_estimate",  models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("purchase_price",         models.DecimalField(decimal_places=2, max_digits=12)),
                ("pvp",                    models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("projected_profit",       models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("priced_at",              models.DateTimeField(blank=True, null=True)),
                ("qr_code_data",           models.CharField(blank=True, max_length=255, null=True)),
                ("sold_at",                models.DateTimeField(blank=True, null=True)),
                ("sale_price",             models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("actual_profit",          models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("branch",                 models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                             related_name="direct_purchases", to="core.branch")),
                ("cash_session",           models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                             related_name="direct_purchases", to="core.cashsession")),
                ("created_by",             models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                             related_name="direct_purchases_created", to=settings.AUTH_USER_MODEL)),
                ("priced_by",              models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                             related_name="direct_purchases_priced", to=settings.AUTH_USER_MODEL)),
                ("sale_cash_session",      models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                             related_name="direct_sales", to="core.cashsession")),
                ("sold_by",                models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                             related_name="direct_purchases_sold", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Compra Directa", "verbose_name_plural": "Compras Directas",
                     "ordering": ["-created_at"]},
        ),

        # ── DirectPurchasePhoto ───────────────────────────────────────────
        migrations.CreateModel(
            name="DirectPurchasePhoto",
            fields=[
                ("id",          models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("public_id",   models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("photo",       models.FileField(upload_to="inventory/photos/%Y/%m/")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("purchase",    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                  related_name="photos", to="core.directpurchase")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                  related_name="inventory_photos", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Foto de artículo", "verbose_name_plural": "Fotos de artículos"},
        ),
    ]
