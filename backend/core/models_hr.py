"""
Módulo de Recursos Humanos
============================
Modelos para gestión de empleados conforme a la normativa laboral boliviana:
  - Employee       : ficha del empleado (vinculado a User del sistema)
  - SalaryScale    : escalera salarial configurable (para cajeros nuevos)
  - AttendanceRecord: registro de entrada/salida (reloj marcador digital)
  - SalaryPeriod   : planilla mensual con todos los cálculos de ley
  - VacationPeriod : acumulación y goce de vacaciones
  - EmployeeTermination: baja + cálculo de liquidación

Referencia legal:
  - Ley General del Trabajo (LGT) y sus Decretos Supremos
  - DS 1213 - Bono de Antigüedad (3 SMN × escala)
  - DS 110 - Aguinaldo (= 1 sueldo/año)
  - Reglamento de AFP / Gestora Pública: 12.71% del salario bruto
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


# ─────────────────────────────────────────────────────────────────────────────
# Configuración Global de RRHH  (singleton — solo 1 fila, pk=1)
# ─────────────────────────────────────────────────────────────────────────────
class HRConfig(models.Model):
    """
    Parámetros legales modificables por el dueño sin tocar código.
    """
    # Salario Mínimo Nacional vigente (Bolivia 2024 = Bs. 2,362)
    smn = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("2362.00"),
        verbose_name="Salario Mínimo Nacional (Bs.)",
    )
    # Descuento AFP/Gestora Pública (% del salario bruto)
    afp_rate_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("12.71"),
        verbose_name="Tasa AFP/Gestora (%)",
    )
    # Hora a partir de la cual aplica recargo nocturno
    night_surcharge_start_hour = models.PositiveSmallIntegerField(
        default=20,
        verbose_name="Hora inicio recargo nocturno",
    )
    # % de recargo nocturno
    night_surcharge_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("25.00"),
        verbose_name="Recargo nocturno (%)",
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True,
        verbose_name="Actualizado por",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración RRHH"
        verbose_name_plural = "Configuración RRHH"

    def __str__(self):
        return f"HRConfig — SMN: {self.smn}"

    @classmethod
    def get(cls) -> "HRConfig":
        """Obtiene (o crea) la configuración singleton."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ─────────────────────────────────────────────────────────────────────────────
# Empleado
# ─────────────────────────────────────────────────────────────────────────────
class Employee(models.Model):
    """
    Ficha del empleado vinculada al usuario del sistema.
    Al dar de alta un empleado se asigna su usuario Django existente
    (o se crea uno nuevo si corresponde).
    """
    class ContractType(models.TextChoices):
        INDEFINIDO = "INDEFINIDO", "Indefinido"
        PLAZO_FIJO = "PLAZO_FIJO", "A Plazo Fijo"
        EVENTUAL   = "EVENTUAL",   "Eventual"

    class WorkSchedule(models.TextChoices):
        FULL_TIME = "FULL_TIME", "Tiempo Completo (48h/semana)"
        HALF_TIME = "HALF_TIME", "Medio Tiempo (24h/semana)"

    class Status(models.TextChoices):
        ACTIVE       = "ACTIVE",       "Activo"
        ON_VACATION  = "ON_VACATION",  "De vacaciones"
        SUSPENDED    = "SUSPENDED",    "Suspendido"
        TERMINATED   = "TERMINATED",   "Dado de baja"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # ── Vínculo con el sistema de autenticación ───────────────────────────────
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employee_profile",
        help_text="Cuenta de usuario del sistema asignada a este empleado.",
    )

    # ── Asignación operativa ──────────────────────────────────────────────────
    branch = models.ForeignKey(
        "Branch",
        on_delete=models.PROTECT,
        related_name="employees",
        help_text="Sucursal donde trabaja el empleado.",
    )
    cash_register = models.ForeignKey(
        "CashRegister",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="assigned_employees",
        help_text="Caja asignada (para deslinde de responsabilidades en faltantes).",
    )

    # ── Identidad (KYC laboral) ───────────────────────────────────────────────
    first_name          = models.CharField(max_length=80)
    last_name_paternal  = models.CharField(max_length=80)
    last_name_maternal  = models.CharField(max_length=80, blank=True, default="")
    ci                  = models.CharField(max_length=20, unique=True,
                                           help_text="Cédula de Identidad")
    complemento_ci      = models.CharField(max_length=5, blank=True, default="",
                                           help_text="Complemento CI (1A, 2B…)")
    nua_cua             = models.CharField(
        max_length=30, blank=True, default="",
        help_text="NUA/CUA para aportes AFP/Gestora. Dejar en blanco si no aplica.",
    )
    phone               = models.CharField(max_length=20, blank=True, default="")
    address             = models.TextField(blank=True, default="")

    # ── Contrato y sueldo ─────────────────────────────────────────────────────
    contract_type   = models.CharField(
        max_length=15, choices=ContractType.choices, default=ContractType.INDEFINIDO
    )
    work_schedule   = models.CharField(
        max_length=10, choices=WorkSchedule.choices, default=WorkSchedule.HALF_TIME
    )
    hire_date       = models.DateField(help_text="Fecha de ingreso oficial.")
    trial_end_date  = models.DateField(
        null=True, blank=True,
        help_text="Fin del período de prueba (max 90 días según LGT).",
    )
    base_salary     = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Sueldo básico actual en Bs.",
    )

    # ── Estado ────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.ACTIVE
    )

    # ── Documentación digital (opcionales hasta tener equipo) ─────────────────
    contract_file   = models.FileField(
        upload_to="hr/contracts/%Y/", null=True, blank=True,
        help_text="Contrato firmado (PDF/imagen).",
    )
    ci_scan         = models.FileField(
        upload_to="hr/ci_scans/%Y/",  null=True, blank=True,
        help_text="Carnet de identidad escaneado.",
    )
    domicile_sketch = models.FileField(
        upload_to="hr/domiciles/%Y/", null=True, blank=True,
        help_text="Croquis de domicilio.",
    )

    # ── Auditoría ─────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employees_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Empleado"
        verbose_name_plural = "Empleados"
        ordering = ["last_name_paternal", "first_name"]

    def __str__(self):
        return f"{self.full_name} (CI: {self.ci})"

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name_paternal]
        if self.last_name_maternal:
            parts.append(self.last_name_maternal)
        return " ".join(parts)

    @property
    def seniority_years(self) -> int:
        """Años completos trabajados a la fecha."""
        from datetime import date
        today = date.today()
        h = self.hire_date
        return today.year - h.year - ((today.month, today.day) < (h.month, h.day))

    @property
    def seniority_months(self) -> int:
        """Meses completos trabajados (útil para la escalera salarial)."""
        from datetime import date
        today = date.today()
        h = self.hire_date
        return (today.year - h.year) * 12 + (today.month - h.month)

    @property
    def has_afp(self) -> bool:
        return bool(self.nua_cua)

    @property
    def weekly_hours(self) -> int:
        return 48 if self.work_schedule == self.WorkSchedule.FULL_TIME else 24

    @property
    def daily_hours(self) -> int:
        return 8 if self.work_schedule == self.WorkSchedule.FULL_TIME else 4


# ─────────────────────────────────────────────────────────────────────────────
# Escalera Salarial (para cajeros nuevos con sueldo escalable)
# ─────────────────────────────────────────────────────────────────────────────
class SalaryScale(models.Model):
    """
    Define el sueldo para cada mes trabajado.
    El dueño crea los escalones; el sistema aplica el sueldo correcto
    según los meses cumplidos del empleado.

    Ejemplo:
      mes 1  → Bs. 200
      mes 2  → Bs. 300
      mes 6  → Bs. 500
      mes 12 → SMN/2 (medio tiempo)
    """
    employee     = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="salary_scale"
    )
    month_number = models.PositiveSmallIntegerField(
        help_text="Mes de trabajo a partir del cual aplica este sueldo (1=primer mes)."
    )
    salary       = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Sueldo en Bs. para este escalón.",
    )
    note         = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Escalón Salarial"
        verbose_name_plural = "Escalera Salarial"
        unique_together = [("employee", "month_number")]
        ordering = ["employee", "month_number"]

    def __str__(self):
        return f"{self.employee.ci} | mes {self.month_number} → Bs.{self.salary}"


# ─────────────────────────────────────────────────────────────────────────────
# Registro de Asistencia (Reloj marcador digital)
# ─────────────────────────────────────────────────────────────────────────────
class AttendanceRecord(models.Model):
    """
    Cada fila = 1 día de trabajo de 1 empleado.
    El empleado marca entrada con POST clock-in; el sistema registra la IP.
    Al marcar salida se calculan automáticamente las horas normales,
    extras y nocturnas.
    """
    employee  = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="attendance"
    )
    date      = models.DateField(help_text="Fecha de la jornada.")

    clock_in  = models.DateTimeField()
    clock_out = models.DateTimeField(null=True, blank=True)

    # IP de registro (para validar que está en la sucursal)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    # Calculados al hacer clock-out (guardados para la planilla)
    regular_hours   = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_hours  = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    night_hours     = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Horas trabajadas después de las 20:00.",
    )

    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Registro de Asistencia"
        verbose_name_plural = "Registros de Asistencia"
        unique_together = [("employee", "date")]
        ordering = ["-date"]

    def __str__(self):
        out = self.clock_out.strftime("%H:%M") if self.clock_out else "—"
        return (
            f"{self.employee.ci} | {self.date} "
            f"{self.clock_in.strftime('%H:%M')} → {out}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Planilla Mensual (SalaryPeriod)
# ─────────────────────────────────────────────────────────────────────────────
class SalaryPeriod(models.Model):
    """
    Pre-planilla generada al cierre de cada mes.
    El dueño la revisa (DRAFT), aprueba y marca como pagada.
    Incluye todos los conceptos de ley boliviana.
    """
    class Status(models.TextChoices):
        DRAFT    = "DRAFT",    "Borrador"
        APPROVED = "APPROVED", "Aprobada"
        PAID     = "PAID",     "Pagada"

    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="salary_periods"
    )
    year  = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()   # 1-12

    # ── Snapshots del mes ─────────────────────────────────────────────────────
    base_salary      = models.DecimalField(max_digits=10, decimal_places=2)
    days_worked      = models.PositiveSmallIntegerField(default=0)

    # ── Horas extra (> 8h/día o > 48h/semana) ────────────────────────────────
    overtime_hours   = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    overtime_amount  = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Recargo nocturno (después de las 20:00) ───────────────────────────────
    night_surcharge_hours  = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    night_surcharge_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Bono de antigüedad (DS 1213: 3 SMN × escala) ─────────────────────────
    seniority_years        = models.PositiveSmallIntegerField(default=0)
    seniority_pct          = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    seniority_bonus_base   = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                  help_text="3 × SMN vigente al calcular.")
    seniority_bonus_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Bonos manuales ────────────────────────────────────────────────────────
    performance_bonus      = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                  help_text="Bono puntualidad / fidelización, etc.")
    performance_bonus_note = models.CharField(max_length=255, blank=True, default="")

    # ── Descuentos ────────────────────────────────────────────────────────────
    cash_shortage_deduction      = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                        help_text="Descuento por faltante de caja justificado.")
    cash_shortage_note           = models.CharField(max_length=255, blank=True, default="")
    other_deductions             = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_deductions_note        = models.CharField(max_length=255, blank=True, default="")

    # ── AFP / Gestora Pública (solo si tiene NUA/CUA) ─────────────────────────
    afp_deduction_pct    = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                                help_text="0 si no tiene NUA; 12.71 si tiene AFP.")
    afp_deduction_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Totales calculados ────────────────────────────────────────────────────
    total_gross      = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_salary       = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Estado y aprobación ───────────────────────────────────────────────────
    status      = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="approved_salary_periods",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at     = models.DateTimeField(null=True, blank=True)
    notes       = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Período Salarial"
        verbose_name_plural = "Períodos Salariales"
        unique_together = [("employee", "year", "month")]
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"{self.employee.ci} | {self.year}-{self.month:02d} | {self.status}"


# ─────────────────────────────────────────────────────────────────────────────
# Vacaciones
# ─────────────────────────────────────────────────────────────────────────────
class VacationPeriod(models.Model):
    """
    Período vacacional por año laboral.
    Al cumplir el año, el sistema crea automáticamente el registro
    con los días disponibles según la antigüedad.
    """
    class Status(models.TextChoices):
        ACCRUING  = "ACCRUING",  "Acumulando"
        AVAILABLE = "AVAILABLE", "Disponible"
        SCHEDULED = "SCHEDULED", "Programada"
        TAKEN     = "TAKEN",     "Gozada"

    employee       = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="vacations"
    )
    accrual_year   = models.PositiveSmallIntegerField(
        help_text="Año laboral cumplido (1=primer año, 2=segundo año…)."
    )
    calendar_year  = models.PositiveSmallIntegerField(
        help_text="Año calendario en que se generó el derecho vacacional."
    )
    days_available = models.PositiveSmallIntegerField(
        help_text="Días hábiles de vacación disponibles (15, 20 o 30)."
    )
    days_taken     = models.PositiveSmallIntegerField(default=0)

    # Fechas asignadas por el dueño
    start_date  = models.DateField(null=True, blank=True)
    end_date    = models.DateField(null=True, blank=True)

    status      = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACCRUING
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="approved_vacations",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    notes       = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Período Vacacional"
        verbose_name_plural = "Períodos Vacacionales"
        unique_together = [("employee", "accrual_year")]
        ordering = ["-accrual_year"]

    def __str__(self):
        return f"{self.employee.ci} | año laboral {self.accrual_year} | {self.days_available}d | {self.status}"

    @property
    def days_remaining(self) -> int:
        return max(0, self.days_available - self.days_taken)


# ─────────────────────────────────────────────────────────────────────────────
# Baja de Empleado + Liquidación
# ─────────────────────────────────────────────────────────────────────────────
class EmployeeTermination(models.Model):
    """
    Registro de baja con cálculo de liquidación tentativa.
    Al guardar se inhabilita automáticamente el acceso del empleado.
    """
    class Reason(models.TextChoices):
        VOLUNTARY  = "VOLUNTARY",  "Renuncia voluntaria"
        EMPLOYER   = "EMPLOYER",   "Despido por empleador"
        MUTUAL     = "MUTUAL",     "Mutuo acuerdo"
        JUSTIFIED  = "JUSTIFIED",  "Despido justificado (sin indemnización)"

    employee         = models.OneToOneField(
        Employee, on_delete=models.PROTECT, related_name="termination"
    )
    termination_date = models.DateField()
    reason           = models.CharField(max_length=15, choices=Reason.choices)

    # ── Snapshot al momento de la baja ───────────────────────────────────────
    months_worked         = models.PositiveSmallIntegerField(default=0)
    base_salary_snapshot  = models.DecimalField(max_digits=10, decimal_places=2)

    # ── Cálculo de liquidación ────────────────────────────────────────────────
    # Indemnización: 1 mes de sueldo por año trabajado (solo EMPLOYER/MUTUAL)
    indemnization_months  = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    indemnization_amount  = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Aguinaldo proporcional (meses trabajados en el año / 12 × sueldo)
    aguinaldo_months      = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    aguinaldo_amount      = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Vacaciones no gozadas
    unused_vacation_days  = models.PositiveSmallIntegerField(default=0)
    unused_vacation_amount= models.DecimalField(max_digits=10, decimal_places=2, default=0)

    total_liquidation     = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    notes                    = models.TextField(blank=True, default="")
    created_by               = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="employee_terminations",
    )
    created_at               = models.DateTimeField(auto_now_add=True)
    certificate_generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Baja de Empleado"
        verbose_name_plural = "Bajas de Empleados"

    def __str__(self):
        return f"{self.employee.ci} | baja {self.termination_date} | {self.reason}"


# ─────────────────────────────────────────────────────────────────────────────
# Aguinaldo (DS 110 — "Esfuerzo Bolivia")
# ─────────────────────────────────────────────────────────────────────────────
class AguinaldoPeriod(models.Model):
    """
    Registro de aguinaldo anual por empleado.

    Tipos:
      REGULAR — aguinaldo ordinario (1 sueldo/año, obligatorio).
      DOBLE   — "Esfuerzo Bolivia": segundo aguinaldo cuando el PIB
                 crece > 4.5% (DS 1802 y modificaciones).

    Cálculo:
      base         = sueldo_base al momento del cálculo (snapshot noviembre)
      months_in_period = meses completos trabajados en el año
                         (enero–noviembre si antiguedad >= 1 año;
                          mes_ingreso–noviembre si ingresó durante el año)
      amount       = (base / 12) × months_in_period
      Requisito    : mínimo 90 días trabajados en el año.
    """
    class AguinaldoType(models.TextChoices):
        REGULAR = "REGULAR", "Aguinaldo Regular (DS 110)"
        DOBLE   = "DOBLE",   "Doble Aguinaldo — Esfuerzo Bolivia"

    class Status(models.TextChoices):
        DRAFT    = "DRAFT",    "Borrador"
        APPROVED = "APPROVED", "Aprobado"
        PAID     = "PAID",     "Pagado"

    employee         = models.ForeignKey(
        "Employee", on_delete=models.PROTECT, related_name="aguinaldos"
    )
    year             = models.PositiveSmallIntegerField(
        help_text="Año fiscal al que corresponde el aguinaldo."
    )
    aguinaldo_type   = models.CharField(
        max_length=10, choices=AguinaldoType.choices, default=AguinaldoType.REGULAR
    )

    # ── Snapshot de cálculo ───────────────────────────────────────────────────
    hire_date_snapshot      = models.DateField(
        help_text="Fecha de ingreso al momento del cálculo (para auditoría)."
    )
    base_salary_snapshot    = models.DecimalField(max_digits=10, decimal_places=2)
    months_in_period        = models.DecimalField(
        max_digits=4, decimal_places=2,
        help_text="Meses proporcionales trabajados en el año (max 11 para regular)."
    )
    days_worked_in_year     = models.PositiveSmallIntegerField(
        default=0,
        help_text="Días efectivamente trabajados en el año (mínimo 90 para calificar)."
    )
    qualifies              = models.BooleanField(
        default=True,
        help_text="False si el empleado no cumple los 90 días mínimos."
    )
    amount                 = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Importe calculado: (sueldo/12) × meses_proporcionales."
    )

    # ── Estado y pago ─────────────────────────────────────────────────────────
    status      = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="approved_aguinaldos",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at     = models.DateTimeField(null=True, blank=True)
    notes       = models.TextField(blank=True, default="")

    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Aguinaldo"
        verbose_name_plural = "Aguinaldos"
        unique_together = [("employee", "year", "aguinaldo_type")]
        ordering = ["-year", "employee__last_name_paternal"]

    def __str__(self):
        return (
            f"{self.employee.ci} | {self.aguinaldo_type} {self.year} "
            f"| Bs.{self.amount} | {self.status}"
        )
