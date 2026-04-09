"""
Comando de gestión: generate_monthly_payroll
=============================================
Genera automáticamente la pre-planilla (DRAFT) para todos los empleados
activos del mes indicado. Ideal para ejecutarse el día 1 de cada mes.

Uso:
  python manage.py generate_monthly_payroll              # mes actual
  python manage.py generate_monthly_payroll --year 2026 --month 3
  python manage.py generate_monthly_payroll --dry-run    # solo muestra lo que haría

Cron recomendado (Linux) — día 1 de cada mes a las 07:00:
  0 7 1 * * /ruta/venv/bin/python /ruta/manage.py generate_monthly_payroll >> /var/log/payroll.log 2>&1
"""
from datetime import date

from django.core.management.base import BaseCommand

from core.models_hr import Employee, HRConfig, SalaryPeriod
from core.services.hr_calculator import generate_payroll, apply_salary_scale, check_vacation_accrual


class Command(BaseCommand):
    help = "Genera pre-planillas mensuales para todos los empleados activos."

    def add_arguments(self, parser):
        today = date.today()
        parser.add_argument("--year",    type=int, default=today.year,  help="Año del período (default: año actual).")
        parser.add_argument("--month",   type=int, default=today.month, help="Mes del período (default: mes actual).")
        parser.add_argument("--dry-run", action="store_true", default=False, help="Calcula sin guardar.")
        parser.add_argument("--quiet",   action="store_true", default=False, help="Solo resumen final.")

    def handle(self, *args, **options):
        year    = options["year"]
        month   = options["month"]
        dry_run = options["dry_run"]
        quiet   = options["quiet"]

        if dry_run:
            self.stdout.write(self.style.WARNING(f"[DRY-RUN] Período: {year}-{month:02d}"))

        cfg       = HRConfig.get()
        employees = list(Employee.objects.filter(status=Employee.Status.ACTIVE).select_related("branch"))

        if not employees:
            self.stdout.write("No hay empleados activos.")
            return

        created = 0
        skipped = 0
        scale_updates = 0
        vacation_alerts = []

        for emp in employees:
            # 1. Aplicar escalera salarial si corresponde
            scale_result = apply_salary_scale(emp)
            if scale_result["updated"]:
                scale_updates += 1
                if not quiet:
                    self.stdout.write(self.style.SUCCESS(
                        f"  Escalon salarial: {emp.ci} "
                        f"Bs.{scale_result['old_salary']} → Bs.{scale_result['new_salary']}"
                    ))

            # 2. Verificar acumulación de vacaciones
            vac = check_vacation_accrual(emp)
            if vac and vac["created"]:
                vacation_alerts.append(
                    f"{emp.full_name} ({emp.ci}): {vac['days']} días disponibles (año laboral {vac['years']})"
                )

            # 3. Generar planilla
            if SalaryPeriod.objects.filter(employee=emp, year=year, month=month).exists():
                skipped += 1
                if not quiet:
                    self.stdout.write(f"  Omitido (ya existe): {emp.ci}")
                continue

            data = generate_payroll(emp, year, month, cfg.smn, cfg.afp_rate_pct)
            data_copy = {k: v for k, v in data.items() if k != "employee"}

            if not dry_run:
                SalaryPeriod.objects.create(employee=emp, **data_copy)

            created += 1
            if not quiet:
                net = data_copy["net_salary"]
                self.stdout.write(self.style.SUCCESS(
                    f"  Generada: {emp.ci} | {emp.full_name} | neto: Bs.{net}"
                ))

        # Resumen
        summary = (
            f"Período {year}-{month:02d}: "
            f"{created} planillas {'calculadas (dry-run)' if dry_run else 'creadas'}, "
            f"{skipped} omitidas, "
            f"{scale_updates} escalones salariales aplicados."
        )
        self.stdout.write(self.style.SUCCESS(summary))

        if vacation_alerts:
            self.stdout.write(self.style.WARNING("\n[VACACIONES DISPONIBLES]"))
            for alert in vacation_alerts:
                self.stdout.write(self.style.WARNING(f"  {alert}"))
