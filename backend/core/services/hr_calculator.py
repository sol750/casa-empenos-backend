"""
Calculadora de RRHH — Normativa Laboral Boliviana
====================================================
Funciones puras de cálculo (sin efectos secundarios).
Todas las funciones reciben los datos necesarios como argumentos.

Referencia legal:
  - DS 1213 (Bono de Antigüedad): 3 SMN × escala porcentual
  - LGT Art. 46 (Jornada): 8h/día, 48h/semana; 4h/24h medio tiempo
  - DS 21060 (Horas extra): pago doble
  - LGT Art. 55 (Vacaciones): 15/20/30 días hábiles según antigüedad
  - DS 110 (Aguinaldo): 1 sueldo/año pagado en diciembre
  - Gestora Pública: 12.71% descuento al trabajador
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models_hr import Employee, AttendanceRecord


# ─────────────────────────────────────────────────────────────────────────────
# Escala de Bono de Antigüedad (DS 1213)
# Base: 3 × SMN  ×  porcentaje según años
# ─────────────────────────────────────────────────────────────────────────────
_SENIORITY_SCALE = [
    (25, Decimal("50.00")),
    (20, Decimal("42.00")),
    (15, Decimal("34.00")),
    (11, Decimal("26.00")),
    (8,  Decimal("18.00")),
    (5,  Decimal("11.00")),
    (2,  Decimal("5.00")),
    (0,  Decimal("0.00")),
]


def get_seniority_pct(years: int) -> Decimal:
    """Retorna el % de bono de antigüedad según los años completos trabajados."""
    for min_years, pct in _SENIORITY_SCALE:
        if years >= min_years:
            return pct
    return Decimal("0.00")


def calculate_seniority_bonus(years: int, smn: Decimal) -> dict:
    """
    Calcula el bono de antigüedad mensual.

    Base = 3 × SMN
    Bono = Base × (pct / 100)

    Returns:
        {
            "years": int,
            "pct": Decimal,
            "base": Decimal,    # 3 × SMN
            "amount": Decimal,  # bono mensual a pagar
        }
    """
    pct  = get_seniority_pct(years)
    base = (3 * smn).quantize(Decimal("0.01"))
    amount = (base * pct / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"years": years, "pct": pct, "base": base, "amount": amount}


# ─────────────────────────────────────────────────────────────────────────────
# Escalera Salarial
# ─────────────────────────────────────────────────────────────────────────────
def get_current_scale_salary(employee) -> Decimal | None:
    """
    Devuelve el sueldo que corresponde según los meses trabajados del empleado
    y la escalera salarial definida por el dueño.

    Retorna None si no hay escalera configurada.
    """
    months = employee.seniority_months
    # Buscar el escalón más alto que ya se alcanzó (mes_número <= meses_trabajados)
    scale = (
        employee.salary_scale
        .filter(month_number__lte=max(months, 1))
        .order_by("-month_number")
        .first()
    )
    return scale.salary if scale else None


def apply_salary_scale(employee) -> dict:
    """
    Verifica si el empleado debe pasar al siguiente escalón salarial
    y actualiza base_salary si corresponde.

    Returns:
        {
            "updated": bool,
            "old_salary": Decimal,
            "new_salary": Decimal,
            "month_number": int,
        }
    """
    current = get_current_scale_salary(employee)
    if current is None:
        return {"updated": False, "old_salary": employee.base_salary, "new_salary": employee.base_salary, "month_number": None}

    old_salary = employee.base_salary
    if current > old_salary:
        from core.models_hr import Employee as Emp
        Emp.objects.filter(pk=employee.pk).update(base_salary=current)
        employee.base_salary = current
        return {
            "updated": True,
            "old_salary": old_salary,
            "new_salary": current,
            "month_number": employee.seniority_months,
        }
    return {"updated": False, "old_salary": old_salary, "new_salary": old_salary, "month_number": None}


# ─────────────────────────────────────────────────────────────────────────────
# Cálculo de horas trabajadas desde un registro de asistencia
# ─────────────────────────────────────────────────────────────────────────────
def calculate_attendance_hours(
    clock_in: datetime,
    clock_out: datetime,
    daily_hours: int,
    night_start_hour: int = 20,
) -> dict:
    """
    Calcula horas regulares, extras y nocturnas de una jornada.

    Args:
        clock_in / clock_out : datetimes (timezone-aware)
        daily_hours          : horas diarias según contrato (8 o 4)
        night_start_hour     : hora a partir de la cual aplica recargo (default 20)

    Returns:
        {
            "total_hours":    Decimal,
            "regular_hours":  Decimal,  # hasta el límite contractual
            "overtime_hours": Decimal,  # exceso sobre el límite diario
            "night_hours":    Decimal,  # horas dentro del período nocturno
        }
    """
    total_seconds = (clock_out - clock_in).total_seconds()
    total_hours   = Decimal(str(round(total_seconds / 3600, 4)))

    regular_hours  = min(total_hours, Decimal(str(daily_hours)))
    overtime_hours = max(Decimal("0"), total_hours - Decimal(str(daily_hours)))

    # Contar horas nocturnas (después de night_start_hour hasta medianoche / fin)
    night_hours = Decimal("0")
    cursor = clock_in
    while cursor < clock_out:
        next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        segment_end = min(next_hour, clock_out)
        if cursor.hour >= night_start_hour:
            seg_seconds = (segment_end - cursor).total_seconds()
            night_hours += Decimal(str(round(seg_seconds / 3600, 4)))
        cursor = segment_end

    return {
        "total_hours":    total_hours.quantize(Decimal("0.01")),
        "regular_hours":  regular_hours.quantize(Decimal("0.01")),
        "overtime_hours": overtime_hours.quantize(Decimal("0.01")),
        "night_hours":    night_hours.quantize(Decimal("0.01")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Valor hora
# ─────────────────────────────────────────────────────────────────────────────
def hourly_rate(base_salary: Decimal, work_schedule: str) -> Decimal:
    """
    Valor de 1 hora normal según el sueldo mensual y la jornada.
    Asume 26 días hábiles de trabajo por mes.
    """
    daily_hours = 8 if work_schedule == "FULL_TIME" else 4
    monthly_hours = Decimal(str(26 * daily_hours))
    return (base_salary / monthly_hours).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ─────────────────────────────────────────────────────────────────────────────
# Generador de Planilla Mensual
# ─────────────────────────────────────────────────────────────────────────────
def generate_payroll(employee, year: int, month: int, smn: Decimal, afp_rate: Decimal) -> dict:
    """
    Calcula todos los conceptos de la planilla para un empleado en un mes.

    Args:
        employee   : instancia Employee con asistencias del período ya cargadas
        year/month : período a calcular
        smn        : Salario Mínimo Nacional vigente
        afp_rate   : % descuento AFP (0 si no tiene NUA)

    Returns:
        dict con todos los campos necesarios para crear/actualizar SalaryPeriod
    """
    from core.models_hr import AttendanceRecord

    # ── 1. Obtener asistencias del mes ─────────────────────────────────────
    attendances = list(
        AttendanceRecord.objects
        .filter(employee=employee, date__year=year, date__month=month)
    )

    days_worked       = len([a for a in attendances if a.clock_out is not None])
    total_overtime    = sum((a.overtime_hours for a in attendances), Decimal("0"))
    total_night       = sum((a.night_hours    for a in attendances), Decimal("0"))

    base_salary = employee.base_salary

    # ── 2. Horas extra (× 2 el valor hora) ────────────────────────────────
    h_rate          = hourly_rate(base_salary, employee.work_schedule)
    overtime_amount = (total_overtime * h_rate * 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ── 3. Recargo nocturno (% sobre el valor hora) ───────────────────────
    from core.models_hr import HRConfig
    cfg = HRConfig.get()
    night_surcharge_pct    = cfg.night_surcharge_pct
    night_surcharge_amount = (
        total_night * h_rate * night_surcharge_pct / 100
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ── 4. Bono de antigüedad ─────────────────────────────────────────────
    sen = calculate_seniority_bonus(employee.seniority_years, smn)

    # ── 5. AFP (solo si tiene NUA/CUA) ─────────────────────────────────────
    has_afp            = bool(employee.nua_cua)
    afp_pct            = afp_rate if has_afp else Decimal("0")
    afp_amount         = (base_salary * afp_pct / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ── 6. Totales ─────────────────────────────────────────────────────────
    total_gross = (
        base_salary
        + overtime_amount
        + night_surcharge_amount
        + sen["amount"]
        # performance_bonus y cash_shortage se agregan manualmente después
    ).quantize(Decimal("0.01"))

    total_deductions = afp_amount.quantize(Decimal("0.01"))
    net_salary       = (total_gross - total_deductions).quantize(Decimal("0.01"))

    return {
        "employee":                employee,
        "year":                    year,
        "month":                   month,
        "base_salary":             base_salary,
        "days_worked":             days_worked,
        # Horas extra
        "overtime_hours":          total_overtime,
        "overtime_amount":         overtime_amount,
        # Nocturno
        "night_surcharge_hours":   total_night,
        "night_surcharge_amount":  night_surcharge_amount,
        # Antigüedad
        "seniority_years":         sen["years"],
        "seniority_pct":           sen["pct"],
        "seniority_bonus_base":    sen["base"],
        "seniority_bonus_amount":  sen["amount"],
        # AFP
        "afp_deduction_pct":       afp_pct,
        "afp_deduction_amount":    afp_amount,
        # Totales (sin bonos/descuentos manuales aún)
        "total_gross":             total_gross,
        "total_deductions":        total_deductions,
        "net_salary":              net_salary,
        "status":                  "DRAFT",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Vacaciones
# ─────────────────────────────────────────────────────────────────────────────
def vacation_days_for_years(years: int) -> int:
    """
    Días hábiles de vacación según antigüedad (LGT Art. 55).
      1–5 años   → 15 días
      5–10 años  → 20 días
      +10 años   → 30 días
    """
    if years >= 10:
        return 30
    if years >= 5:
        return 20
    if years >= 1:
        return 15
    return 0


def check_vacation_accrual(employee) -> dict | None:
    """
    Verifica si el empleado acaba de cumplir un año laboral y le corresponde
    un nuevo período vacacional. Crea el registro si no existe.

    Returns None si no hay nuevo período que crear.
    Returns el VacationPeriod creado/existente si el año se cumplió.
    """
    from core.models_hr import VacationPeriod

    years = employee.seniority_years
    if years < 1:
        return None

    days = vacation_days_for_years(years)
    today = date.today()

    period, created = VacationPeriod.objects.get_or_create(
        employee=employee,
        accrual_year=years,
        defaults={
            "calendar_year":  today.year,
            "days_available": days,
            "status":         VacationPeriod.Status.AVAILABLE,
        },
    )
    return {"created": created, "period": period, "days": days, "years": years}


# ─────────────────────────────────────────────────────────────────────────────
# Liquidación por Baja
# ─────────────────────────────────────────────────────────────────────────────
def calculate_liquidation(employee, termination_date: date, reason: str) -> dict:
    """
    Calcula la liquidación tentativa según la LGT boliviana.

    Conceptos:
      Indemnización:   1 mes de sueldo por año trabajado (solo EMPLOYER / MUTUAL)
      Aguinaldo:       meses_trabajados_en_el_año / 12 × sueldo_base
      Vacaciones:      días no gozados × (sueldo / 30)

    Returns:
        {
            "months_worked":          int,
            "base_salary_snapshot":   Decimal,
            "indemnization_months":   Decimal,
            "indemnization_amount":   Decimal,
            "aguinaldo_months":       Decimal,
            "aguinaldo_amount":       Decimal,
            "unused_vacation_days":   int,
            "unused_vacation_amount": Decimal,
            "total_liquidation":      Decimal,
        }
    """
    h = employee.hire_date
    months_worked = (
        (termination_date.year - h.year) * 12
        + (termination_date.month - h.month)
    )
    base = employee.base_salary

    # Indemnización: solo aplica si no es renuncia voluntaria ni justificado
    if reason in ("EMPLOYER", "MUTUAL"):
        years_for_indemnization = Decimal(str(months_worked)) / 12
        indem_amount = (years_for_indemnization * base).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        years_for_indemnization = Decimal("0")
        indem_amount = Decimal("0")

    # Aguinaldo proporcional (meses transcurridos del año actual / 12)
    months_this_year = termination_date.month
    aguinaldo_months = Decimal(str(months_this_year)) / 12
    aguinaldo_amount = (aguinaldo_months * base).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Vacaciones no gozadas
    from core.models_hr import VacationPeriod
    unused_days = sum(
        max(0, vp.days_available - vp.days_taken)
        for vp in employee.vacations.filter(
            status__in=[VacationPeriod.Status.AVAILABLE, VacationPeriod.Status.SCHEDULED]
        )
    )
    daily_salary   = (base / 30).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    vacation_amount = (Decimal(str(unused_days)) * daily_salary).quantize(Decimal("0.01"))

    total = (indem_amount + aguinaldo_amount + vacation_amount).quantize(Decimal("0.01"))

    return {
        "months_worked":          months_worked,
        "base_salary_snapshot":   base,
        "indemnization_months":   years_for_indemnization.quantize(Decimal("0.01")),
        "indemnization_amount":   indem_amount,
        "aguinaldo_months":       aguinaldo_months.quantize(Decimal("0.01")),
        "aguinaldo_amount":       aguinaldo_amount,
        "unused_vacation_days":   unused_days,
        "unused_vacation_amount": vacation_amount,
        "total_liquidation":      total,
    }
