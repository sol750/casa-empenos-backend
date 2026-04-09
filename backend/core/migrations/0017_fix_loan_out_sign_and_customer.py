"""
Migración 0017 — DOS objetivos:

1. DATA FIX: Normalizar la convención de signos en CashMovement.
   Los movimientos LOAN_OUT fueron guardados con amount negativo por error.
   La convención correcta: todos los amounts POSITIVOS; la dirección la da el
   campo movement_type (_IN suma, _OUT resta al calcular saldo).

2. SCHEMA: Crear los modelos Customer, CustomerReference, WhatsAppMessage
   y agregar la FK nullable customer_id a PawnContract.
"""
import uuid
import django.db.models.deletion
import django.core.validators
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_pawncontract_investor"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── 1. DATA FIX: corregir amounts negativos en LOAN_OUT ──────────────
        migrations.RunSQL(
            sql="""
                UPDATE core_cashmovement
                SET amount = ABS(amount)
                WHERE movement_type = 'LOAN_OUT'
                  AND amount < 0;
            """,
            reverse_sql="""
                -- No revertimos: mantener amounts positivos es la convención correcta.
                -- Si necesitas rollback completo elimina los registros manualmente.
                SELECT 1;
            """,
        ),

        # ── 2. SCHEMA: Modelo Customer ────────────────────────────────────────
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("ci", models.CharField(
                    db_index=True, max_length=30, unique=True,
                    help_text="Cédula de identidad — llave única del cliente",
                )),
                ("first_name",         models.CharField(max_length=80)),
                ("last_name_paternal", models.CharField(max_length=80)),
                ("last_name_maternal", models.CharField(blank=True, default="", max_length=80)),
                ("birth_date",         models.DateField(help_text="Necesaria para validar mayoría de edad")),
                ("photo_face", models.ImageField(
                    blank=True, null=True,
                    upload_to="customers/faces/%Y/%m/",
                    help_text="Foto del rostro del cliente",
                )),
                ("photo_ci", models.ImageField(
                    blank=True, null=True,
                    upload_to="customers/ci_docs/%Y/%m/",
                    help_text="Foto/escaneo del documento de identidad",
                )),
                ("phone",   models.CharField(max_length=20, help_text="Formato internacional: +591XXXXXXXX")),
                ("email",   models.EmailField(blank=True, default="")),
                ("address", models.TextField(blank=True, default="")),
                ("gps_lat", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("gps_lon", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("is_blacklisted",   models.BooleanField(default=False)),
                ("blacklist_reason", models.TextField(blank=True, default="")),
                ("category", models.CharField(
                    choices=[("BRONCE", "Bronce"), ("PLATA", "Plata"), ("ORO", "Oro")],
                    default="BRONCE", max_length=10,
                )),
                ("score", models.IntegerField(
                    default=50,
                    validators=[
                        django.core.validators.MinValueValidator(0),
                        django.core.validators.MaxValueValidator(100),
                    ],
                    help_text="Puntaje 0-100 calculado por el motor de scoring",
                )),
                ("total_contracts",        models.PositiveIntegerField(default=0)),
                ("late_payments_count",    models.PositiveIntegerField(default=0)),
                ("on_time_payments_count", models.PositiveIntegerField(default=0)),
                ("created_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="customers_created",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Cliente", "verbose_name_plural": "Clientes"},
        ),

        # ── 3. SCHEMA: Modelo CustomerReference ───────────────────────────────
        migrations.CreateModel(
            name="CustomerReference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("customer", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="references",
                    to="core.customer",
                )),
                ("full_name",    models.CharField(max_length=120)),
                ("phone",        models.CharField(max_length=20)),
                ("relationship", models.CharField(
                    blank=True, default="", max_length=60,
                    help_text="Familiar, Amigo, Colega, etc.",
                )),
            ],
            options={"verbose_name": "Referencia de Cliente", "verbose_name_plural": "Referencias de Cliente"},
        ),

        # ── 4. SCHEMA: Modelo WhatsAppMessage ─────────────────────────────────
        migrations.CreateModel(
            name="WhatsAppMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("customer", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="whatsapp_messages",
                    to="core.customer",
                )),
                ("contract", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="whatsapp_messages",
                    to="core.pawncontract",
                )),
                ("event_type", models.CharField(
                    choices=[
                        ("DUE_REMINDER",    "Recordatorio Vencimiento (3 días)"),
                        ("OVERDUE_NOTICE",  "Aviso de Mora"),
                        ("PAYMENT_CONFIRM", "Confirmación de Pago"),
                        ("WELCOME",         "Bienvenida"),
                    ],
                    max_length=30,
                )),
                ("status", models.CharField(
                    choices=[
                        ("PENDING",   "Pendiente de envío"),
                        ("SENT",      "Enviado"),
                        ("DELIVERED", "Entregado"),
                        ("READ",      "Leído"),
                        ("FAILED",    "Fallido"),
                    ],
                    default="PENDING",
                    max_length=20,
                )),
                ("phone_to",      models.CharField(max_length=20)),
                ("message_body",  models.TextField()),
                ("scheduled_for", models.DateTimeField(help_text="Cuándo debe enviarse este mensaje")),
                ("sent_at",       models.DateTimeField(blank=True, null=True)),
                ("wa_message_id", models.CharField(blank=True, default="", max_length=100)),
                ("error_log",     models.TextField(blank=True, default="")),
                ("created_at",    models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "Mensaje WhatsApp", "verbose_name_plural": "Cola de WhatsApp"},
        ),
        migrations.AddIndex(
            model_name="whatsappmessage",
            index=models.Index(fields=["status", "scheduled_for"], name="wa_status_schedule_idx"),
        ),

        # ── 5. SCHEMA: FK customer en PawnContract (nullable) ─────────────────
        migrations.AddField(
            model_name="pawncontract",
            name="customer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contracts",
                to="core.customer",
            ),
        ),
    ]
