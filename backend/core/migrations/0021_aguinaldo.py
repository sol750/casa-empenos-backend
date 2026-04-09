"""
0021 – Aguinaldo (DS 110 + Esfuerzo Bolivia)
===============================================
Crea la tabla AguinaldoPeriod para registro y control de pagos
de aguinaldo regular y doble aguinaldo.
"""
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_hr_module"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AguinaldoPeriod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("year", models.PositiveSmallIntegerField(
                    help_text="Año fiscal al que corresponde el aguinaldo."
                )),
                ("aguinaldo_type", models.CharField(
                    choices=[("REGULAR", "Aguinaldo Regular (DS 110)"), ("DOBLE", "Doble Aguinaldo — Esfuerzo Bolivia")],
                    default="REGULAR", max_length=10,
                )),
                ("hire_date_snapshot", models.DateField()),
                ("base_salary_snapshot", models.DecimalField(decimal_places=2, max_digits=10)),
                ("months_in_period", models.DecimalField(decimal_places=2, max_digits=4)),
                ("days_worked_in_year", models.PositiveSmallIntegerField(default=0)),
                ("qualifies", models.BooleanField(default=True)),
                ("amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("status", models.CharField(
                    choices=[("DRAFT", "Borrador"), ("APPROVED", "Aprobado"), ("PAID", "Pagado")],
                    default="DRAFT", max_length=10,
                )),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="approved_aguinaldos",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("employee", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="aguinaldos",
                    to="core.employee",
                )),
            ],
            options={
                "verbose_name": "Aguinaldo",
                "verbose_name_plural": "Aguinaldos",
                "ordering": ["-year", "employee__last_name_paternal"],
                "unique_together": {("employee", "year", "aguinaldo_type")},
            },
        ),
    ]
