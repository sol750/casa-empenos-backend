"""
0020 – Módulo de Recursos Humanos
===================================
Crea las tablas:
  - HRConfig          (singleton de parámetros legales)
  - Employee          (ficha del empleado)
  - SalaryScale       (escalera salarial configurable)
  - AttendanceRecord  (reloj marcador digital)
  - SalaryPeriod      (planilla mensual)
  - VacationPeriod    (acumulación y goce de vacaciones)
  - EmployeeTermination (baja + liquidación)
"""
import uuid
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_mora_module"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── HRConfig ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="HRConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("smn", models.DecimalField(decimal_places=2, default=Decimal("2362.00"), max_digits=10, verbose_name="Salario Mínimo Nacional (Bs.)")),
                ("afp_rate_pct", models.DecimalField(decimal_places=2, default=Decimal("12.71"), max_digits=5, verbose_name="Tasa AFP/Gestora (%)")),
                ("night_surcharge_start_hour", models.PositiveSmallIntegerField(default=20, verbose_name="Hora inicio recargo nocturno")),
                ("night_surcharge_pct", models.DecimalField(decimal_places=2, default=Decimal("25.00"), max_digits=5, verbose_name="Recargo nocturno (%)")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name="Actualizado por")),
            ],
            options={"verbose_name": "Configuración RRHH", "verbose_name_plural": "Configuración RRHH"},
        ),

        # ── Employee ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Employee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("first_name", models.CharField(max_length=80)),
                ("last_name_paternal", models.CharField(max_length=80)),
                ("last_name_maternal", models.CharField(blank=True, default="", max_length=80)),
                ("ci", models.CharField(max_length=20, unique=True)),
                ("complemento_ci", models.CharField(blank=True, default="", max_length=5)),
                ("nua_cua", models.CharField(blank=True, default="", help_text="NUA/CUA para aportes AFP/Gestora.", max_length=30)),
                ("phone", models.CharField(blank=True, default="", max_length=20)),
                ("address", models.TextField(blank=True, default="")),
                ("contract_type", models.CharField(choices=[("INDEFINIDO", "Indefinido"), ("PLAZO_FIJO", "A Plazo Fijo"), ("EVENTUAL", "Eventual")], default="INDEFINIDO", max_length=15)),
                ("work_schedule", models.CharField(choices=[("FULL_TIME", "Tiempo Completo (48h/semana)"), ("HALF_TIME", "Medio Tiempo (24h/semana)")], default="HALF_TIME", max_length=10)),
                ("hire_date", models.DateField()),
                ("trial_end_date", models.DateField(blank=True, null=True)),
                ("base_salary", models.DecimalField(decimal_places=2, max_digits=10)),
                ("status", models.CharField(choices=[("ACTIVE", "Activo"), ("ON_VACATION", "De vacaciones"), ("SUSPENDED", "Suspendido"), ("TERMINATED", "Dado de baja")], default="ACTIVE", max_length=15)),
                ("contract_file", models.FileField(blank=True, null=True, upload_to="hr/contracts/%Y/")),
                ("ci_scan", models.FileField(blank=True, null=True, upload_to="hr/ci_scans/%Y/")),
                ("domicile_sketch", models.FileField(blank=True, null=True, upload_to="hr/domiciles/%Y/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="employees", to="core.branch")),
                ("cash_register", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="assigned_employees", to="core.cashregister")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="employees_created", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="employee_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Empleado", "verbose_name_plural": "Empleados", "ordering": ["last_name_paternal", "first_name"]},
        ),

        # ── SalaryScale ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name="SalaryScale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("month_number", models.PositiveSmallIntegerField()),
                ("salary", models.DecimalField(decimal_places=2, max_digits=10)),
                ("note", models.CharField(blank=True, default="", max_length=255)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="salary_scale", to="core.employee")),
            ],
            options={"verbose_name": "Escalón Salarial", "verbose_name_plural": "Escalera Salarial", "ordering": ["employee", "month_number"], "unique_together": {("employee", "month_number")}},
        ),

        # ── AttendanceRecord ──────────────────────────────────────────────────
        migrations.CreateModel(
            name="AttendanceRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("date", models.DateField()),
                ("clock_in", models.DateTimeField()),
                ("clock_out", models.DateTimeField(blank=True, null=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("regular_hours", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("overtime_hours", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("night_hours", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("note", models.CharField(blank=True, default="", max_length=255)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attendance", to="core.employee")),
            ],
            options={"verbose_name": "Registro de Asistencia", "verbose_name_plural": "Registros de Asistencia", "ordering": ["-date"], "unique_together": {("employee", "date")}},
        ),

        # ── SalaryPeriod ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name="SalaryPeriod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("year", models.PositiveSmallIntegerField()),
                ("month", models.PositiveSmallIntegerField()),
                ("base_salary", models.DecimalField(decimal_places=2, max_digits=10)),
                ("days_worked", models.PositiveSmallIntegerField(default=0)),
                ("overtime_hours", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("overtime_amount", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("night_surcharge_hours", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("night_surcharge_amount", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("seniority_years", models.PositiveSmallIntegerField(default=0)),
                ("seniority_pct", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("seniority_bonus_base", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("seniority_bonus_amount", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("performance_bonus", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("performance_bonus_note", models.CharField(blank=True, default="", max_length=255)),
                ("cash_shortage_deduction", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("cash_shortage_note", models.CharField(blank=True, default="", max_length=255)),
                ("other_deductions", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("other_deductions_note", models.CharField(blank=True, default="", max_length=255)),
                ("afp_deduction_pct", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("afp_deduction_amount", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("total_gross", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("total_deductions", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("net_salary", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("status", models.CharField(choices=[("DRAFT", "Borrador"), ("APPROVED", "Aprobada"), ("PAID", "Pagada")], default="DRAFT", max_length=10)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_salary_periods", to=settings.AUTH_USER_MODEL)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="salary_periods", to="core.employee")),
            ],
            options={"verbose_name": "Período Salarial", "verbose_name_plural": "Períodos Salariales", "ordering": ["-year", "-month"], "unique_together": {("employee", "year", "month")}},
        ),

        # ── VacationPeriod ────────────────────────────────────────────────────
        migrations.CreateModel(
            name="VacationPeriod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("accrual_year", models.PositiveSmallIntegerField()),
                ("calendar_year", models.PositiveSmallIntegerField()),
                ("days_available", models.PositiveSmallIntegerField()),
                ("days_taken", models.PositiveSmallIntegerField(default=0)),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("ACCRUING", "Acumulando"), ("AVAILABLE", "Disponible"), ("SCHEDULED", "Programada"), ("TAKEN", "Gozada")], default="ACCRUING", max_length=10)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_vacations", to=settings.AUTH_USER_MODEL)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="vacations", to="core.employee")),
            ],
            options={"verbose_name": "Período Vacacional", "verbose_name_plural": "Períodos Vacacionales", "ordering": ["-accrual_year"], "unique_together": {("employee", "accrual_year")}},
        ),

        # ── EmployeeTermination ───────────────────────────────────────────────
        migrations.CreateModel(
            name="EmployeeTermination",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("termination_date", models.DateField()),
                ("reason", models.CharField(choices=[("VOLUNTARY", "Renuncia voluntaria"), ("EMPLOYER", "Despido por empleador"), ("MUTUAL", "Mutuo acuerdo"), ("JUSTIFIED", "Despido justificado (sin indemnización)")], max_length=15)),
                ("months_worked", models.PositiveSmallIntegerField(default=0)),
                ("base_salary_snapshot", models.DecimalField(decimal_places=2, max_digits=10)),
                ("indemnization_months", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("indemnization_amount", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("aguinaldo_months", models.DecimalField(decimal_places=2, default=0, max_digits=4)),
                ("aguinaldo_amount", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("unused_vacation_days", models.PositiveSmallIntegerField(default=0)),
                ("unused_vacation_amount", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("total_liquidation", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("certificate_generated_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="employee_terminations", to=settings.AUTH_USER_MODEL)),
                ("employee", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="termination", to="core.employee")),
            ],
            options={"verbose_name": "Baja de Empleado", "verbose_name_plural": "Bajas de Empleados"},
        ),
    ]
