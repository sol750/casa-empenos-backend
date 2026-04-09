"""
Migración 0018 — Mejoras al Flujo de Caja

1. CashRegister: nuevo tipo VAULT, umbrales min/max, constraint actualizado
2. CashMovement: nuevos tipos PURCHASE_OUT, EXPENSE_OUT, VAULT_IN, VAULT_OUT
3. Investor: campo profit_rate_pct
4. NUEVO modelo CashDenomination (matriz de billetes/monedas)
5. NUEVO modelo CashExpense (detalle de gasto operativo con recibo)
"""
import uuid
import decimal
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_fix_loan_out_sign_and_customer"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── 1. CashRegister: quitar constraint viejo, agregar campos, nuevo constraint ──
        migrations.RemoveConstraint(
            model_name="cashregister",
            name="cashregister_branch_required_when_branch_type",
        ),
        migrations.AddField(
            model_name="cashregister",
            name="min_balance",
            field=models.DecimalField(
                decimal_places=2, default=decimal.Decimal("1000.00"), max_digits=12,
                help_text="Mínimo operativo. Si el saldo baja de aquí se genera alerta de fondeo.",
            ),
        ),
        migrations.AddField(
            model_name="cashregister",
            name="max_balance",
            field=models.DecimalField(
                decimal_places=2, default=decimal.Decimal("4000.00"), max_digits=12,
                help_text="Máximo operativo. Si el saldo sube de aquí se genera alerta de saturación.",
            ),
        ),
        migrations.AlterField(
            model_name="cashregister",
            name="register_type",
            field=models.CharField(
                choices=[
                    ("BRANCH", "Caja Sucursal"),
                    ("VAULT",  "Bóveda"),
                    ("GLOBAL", "Global"),
                ],
                default="BRANCH",
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="cashregister",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(register_type="GLOBAL", branch__isnull=True)
                    | models.Q(register_type="BRANCH", branch__isnull=False)
                    | models.Q(register_type="VAULT",  branch__isnull=False)
                ),
                name="cashregister_branch_required_when_branch_type",
            ),
        ),

        # ── 2. CashMovement: nuevos tipos ─────────────────────────────────────
        migrations.AlterField(
            model_name="cashmovement",
            name="movement_type",
            field=models.CharField(
                choices=[
                    ("TRANSFER_IN",    "Transferencia Entrante"),
                    ("TRANSFER_OUT",   "Transferencia Saliente"),
                    ("ADJUSTMENT_IN",  "Ajuste Sobrante"),
                    ("ADJUSTMENT_OUT", "Ajuste Faltante"),
                    ("LOAN_OUT",       "CN – Desembolso de Contrato"),
                    ("PAYMENT_IN",     "CC/UC – Cobro de Contrato"),
                    ("PURCHASE_OUT",   "CD – Compra Directa"),
                    ("EXPENSE_OUT",    "G – Gasto Operativo"),
                    ("VAULT_IN",       "Ingreso a Bóveda"),
                    ("VAULT_OUT",      "Salida de Bóveda"),
                ],
                max_length=20,
            ),
        ),

        # ── 3. Investor: profit_rate_pct ──────────────────────────────────────
        migrations.AddField(
            model_name="investor",
            name="profit_rate_pct",
            field=models.DecimalField(
                decimal_places=2, default=decimal.Decimal("50.00"), max_digits=5,
                help_text="Porcentaje de la utilidad (interés) que corresponde al inversionista.",
            ),
        ),

        # ── 4. CashDenomination ───────────────────────────────────────────────
        migrations.CreateModel(
            name="CashDenomination",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("cash_session", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="denominations",
                    to="core.cashsession",
                )),
                ("denom_type", models.CharField(
                    choices=[("OPENING", "Apertura"), ("CLOSING", "Cierre")],
                    max_length=10,
                )),
                ("b_200", models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.200")),
                ("b_100", models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.100")),
                ("b_50",  models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.50")),
                ("b_20",  models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.20")),
                ("b_10",  models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.10")),
                ("c_5",   models.PositiveIntegerField(default=0, verbose_name="Monedas Bs.5")),
                ("c_2",   models.PositiveIntegerField(default=0, verbose_name="Monedas Bs.2")),
                ("c_1",   models.PositiveIntegerField(default=0, verbose_name="Monedas Bs.1")),
                ("counted_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="denominations_counted",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Denominación de Caja",
                "verbose_name_plural": "Denominaciones de Caja",
            },
        ),
        migrations.AlterUniqueTogether(
            name="cashdenomination",
            unique_together={("cash_session", "denom_type")},
        ),

        # ── 5. CashExpense ────────────────────────────────────────────────────
        migrations.CreateModel(
            name="CashExpense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("cash_movement", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="expense_detail",
                    to="core.cashmovement",
                )),
                ("category", models.CharField(
                    choices=[
                        ("UTILITIES",   "Servicios (luz, agua, internet)"),
                        ("CLEANING",    "Limpieza"),
                        ("SUPPLIES",    "Útiles de oficina"),
                        ("MAINTENANCE", "Mantenimiento"),
                        ("SALARY",      "Salario / Honorario"),
                        ("OTHER",       "Otro"),
                    ],
                    default="OTHER",
                    max_length=20,
                )),
                ("description", models.TextField(help_text="Descripción obligatoria del gasto")),
                ("receipt", models.ImageField(
                    blank=True, null=True,
                    upload_to="expenses/receipts/%Y/%m/",
                    help_text="Foto o escaneo del comprobante",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Gasto Operativo",
                "verbose_name_plural": "Gastos Operativos",
            },
        ),
    ]
