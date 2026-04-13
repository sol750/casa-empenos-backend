# ARCHITECTURE GUIDE — CASA DE EMPEÑOS
> **Verdad del Proyecto** — Mapa definitivo del backend Django 5.2 + DRF 3.16 + PostgreSQL 16  
> Última actualización: 2026-04-13

---

## ÍNDICE

1. [Stack Tecnológico](#1-stack-tecnológico)
2. [Estructura de Directorios](#2-estructura-de-directorios)
3. [Configuración del Sistema](#3-configuración-del-sistema)
4. [Modelos de Base de Datos](#4-modelos-de-base-de-datos)
5. [Servicios y Lógica de Negocio](#5-servicios-y-lógica-de-negocio)
6. [API — Endpoints Completos](#6-api--endpoints-completos)
7. [RBAC — Roles y Permisos](#7-rbac--roles-y-permisos)
8. [Flujos Operativos Clave](#8-flujos-operativos-clave)
9. [Constantes y Parámetros de Negocio](#9-constantes-y-parámetros-de-negocio)
10. [Historial de Migraciones](#10-historial-de-migraciones)
11. [Integraciones Externas](#11-integraciones-externas)

---

## 1. STACK TECNOLÓGICO

| Componente | Versión | Notas |
|---|---|---|
| Python | 3.11+ | |
| Django | 5.2.x | ORM + Admin |
| Django REST Framework | 3.16.1 | API JSON |
| PostgreSQL | 16 | Base de datos principal |
| JWT Auth | djangorestframework-simplejwt | Autenticación stateless |
| drf-spectacular | — | OpenAPI / Swagger |
| django-cors-headers | — | CORS para frontend |
| Pillow | — | Imágenes (fotos clientes, recibos) |
| python-dateutil | — | relativedelta para cálculos de fechas |

**Zona horaria:** `America/La_Paz` (Bolivia, UTC-4). Todos los `DateTimeField` usan `USE_TZ=True`.  
**Idioma:** `es-bo` (Español Bolivia).

---

## 2. ESTRUCTURA DE DIRECTORIOS

```
casa_empenos/
├── backend/
│   ├── configuracion/
│   │   └── settings.py              ← Configuración central
│   ├── core/
│   │   ├── models.py                ← Modelos principales (caja, contratos, clientes)
│   │   ├── models_hr.py             ← Módulo RRHH
│   │   ├── models_security.py       ← Roles y acceso
│   │   ├── models_inventory.py      ← Compra directa / vitrina
│   │   ├── models_mvi.py            ← Motor de Valoración Inteligente
│   │   ├── migrations/              ← 25 migraciones (0001 → 0025)
│   │   ├── api/
│   │   │   ├── urls.py              ← Registro de todos los endpoints
│   │   │   ├── security.py          ← Helpers RBAC (require_roles, etc.)
│   │   │   ├── views/               ← ~58 archivos de vistas
│   │   │   └── serializers/         ← ~20 serializadores
│   │   └── services/                ← Lógica de negocio pura
│   │       ├── interest_calc.py
│   │       ├── interest_policy.py
│   │       ├── credit_line_calc.py
│   │       ├── contract_state.py
│   │       ├── contract_numbering.py
│   │       ├── scoring_engine.py
│   │       ├── default_processor.py
│   │       ├── pawn_amortization.py
│   │       ├── mvi_engine.py
│   │       ├── cash_alerts.py
│   │       ├── hr_calculator.py
│   │       ├── whatsapp_sender.py
│   │       └── whatsapp_humanizer.py
```

---

## 3. CONFIGURACIÓN DEL SISTEMA

### Base de datos
```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME":     env("DB_NAME"),
        "USER":     env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST":     env("DB_HOST"),
        "PORT":     env("DB_PORT"),
    }
}
```

### Aplicaciones registradas
```python
INSTALLED_APPS = [
    # Django core
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    # Proyecto
    "sucursales", "cuentas", "libro_mayor", "caja", "core",
    # Third-party
    "rest_framework", "drf_spectacular", "corsheaders",
]
```

### REST Framework
```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES":     ["rest_framework.permissions.IsAuthenticated"],
}
```

### WhatsApp (Meta Business API)
```python
WHATSAPP_TOKEN              = env("WHATSAPP_TOKEN")       # Bearer token
WHATSAPP_PHONE_ID           = env("WHATSAPP_PHONE_ID")    # Phone number ID
WHATSAPP_API_VERSION        = "v20.0"
WHATSAPP_OFFICE_HOURS_START = 8     # Hora inicio envío
WHATSAPP_OFFICE_HOURS_END   = 18    # Hora fin envío
WHATSAPP_SEND_ON_WEEKENDS   = False
WHATSAPP_DELAY_MIN          = 30    # segundos de delay humanizado
WHATSAPP_DELAY_MAX          = 90
```

---

## 4. MODELOS DE BASE DE DATOS

### 4.1 Infraestructura — Sucursales y Cajas

```
Branch (Sucursal)
├── name                  CharField(120)
├── code                  CharField(20) UNIQUE  — ej: PT1, SC1
├── is_active             BooleanField default=True
├── grace_period_days     PositiveSmallInt default=30  — días gracia antes de mora
└── created_at            DateTimeField auto

BranchCounter (Contador atómico por sucursal)
└── branch            OneToOne → Branch
└── pawn_contract_seq PositiveInt default=0

CashRegister (Caja)
├── public_id         UUID unique
├── name              CharField(60)
├── register_type     BRANCH | VAULT | GLOBAL
├── branch            FK → Branch (null si GLOBAL)
├── is_active         BooleanField default=True
├── min_balance       Decimal default=1000.00  — alerta fondeo
└── max_balance       Decimal default=4000.00  — alerta saturación

CashSession (Sesión de Caja)
├── public_id                UUID unique
├── cash_register            FK → CashRegister
├── branch                   FK → Branch
├── opened_by / opened_at    FK User / DateTimeField auto
├── opening_amount           Decimal
├── status                   OPEN | CLOSED
├── closed_by / closed_at    FK User / DateTimeField
├── closing_counted_amount   Decimal — conteo físico
├── closing_expected_amount  Decimal — saldo lógico calculado
├── closing_diff_amount      Decimal — diferencia
└── closing_notes            TextField
    CONSTRAINT: unique OPEN por cash_register
    PROPERTY:   expected_balance → opening + IN - OUT (dinámico si OPEN, guardado si CLOSED)

CashMovement (Movimiento de Caja)
├── public_id         UUID unique
├── cash_session      FK → CashSession
├── cash_register     FK → CashRegister
├── branch            FK → Branch
├── movement_type     Ver tabla abajo
├── amount            Decimal (siempre positivo, dirección = tipo)
├── performed_by      FK → User
├── performed_at      DateTimeField auto
└── note              CharField(255)
```

**Tipos de Movimiento (`movement_type`):**

| Código | Label | Dirección |
|---|---|---|
| `CAPITAL_IN` | Inyección de Capital (dueño) | +IN |
| `CAPITAL_OUT` | Retiro de Capital / Utilidad (dueño) | -OUT |
| `TRANSFER_IN` | Transferencia Entrante | +IN |
| `TRANSFER_OUT` | Transferencia Saliente | -OUT |
| `ADJUSTMENT_IN` | Ajuste Sobrante | +IN |
| `ADJUSTMENT_OUT` | Ajuste Faltante | -OUT |
| `LOAN_OUT` | CN — Desembolso de Contrato | -OUT |
| `PAYMENT_IN` | CC/UC — Cobro de Contrato | +IN |
| `PURCHASE_OUT` | CD — Compra Directa | -OUT |
| `EXPENSE_OUT` | G — Gasto Operativo | -OUT |
| `VAULT_IN` | Ingreso a Bóveda | +IN |
| `VAULT_OUT` | Salida de Bóveda | -OUT |

> **Regla:** `expected_balance = opening_amount + Σ(_IN) - Σ(_OUT)` usando `movement_type__endswith`.

---

### 4.2 Contratos de Empeño

```
PawnContract (Contrato)
├── public_id              UUID unique
├── contract_number        CharField UNIQUE  — ej: PT1-000001
├── branch                 FK → Branch
├── created_by             FK → User
├── created_at             DateTimeField auto
├── status                 ACTIVE | CLOSED | DEFAULTED | CANCELLED | EN_VENTA | SOLD
├── customer               FK → Customer (null=legacy)
├── customer_full_name     CharField(120) — snapshot al crear
├── customer_ci            CharField(30)  — snapshot al crear
├── principal_amount       Decimal        — capital prestado total
├── interest_rate_monthly  Decimal default=8.00 (%)
├── start_date             DateField
├── due_date               DateField      — fecha de vencimiento
├── interest_mode          FIXED | PROMO  default=FIXED
├── promo_note             CharField(255)
├── disbursed_cash_session FK → CashSession
├── defaulted_at           DateTimeField null
├── interest_accrued_until DateField null — base para cálculo de interés
└── investor               FK → Investor null

PawnItem (Artículo empeñado)
├── public_id      UUID unique
├── contract       FK → PawnContract (CASCADE)
├── category       LAPTOP | PHONE | JEWELRY | APPLIANCE | CONSOLE | INSTRUMENT | OTHER
├── description    TextField
├── attributes     JSONField (specs técnicas: marca, modelo, GB, karat, gramos…)
├── condition      EXCELLENT | GOOD | WORN | DAMAGED  default=GOOD
├── has_box        BooleanField
├── has_charger    BooleanField
├── observations   TextField
├── loan_amount    Decimal null — capital prestado atribuido a este artículo
└── created_at     DateTimeField auto

PawnPayment (Pago/Cobro)
├── public_id      UUID unique
├── contract       FK → PawnContract
├── cash_session   FK → CashSession
├── paid_at        DateTimeField auto
├── paid_by        FK → User
├── amount         Decimal — total pagado
├── interest_paid  Decimal — porción que fue interés
├── principal_paid Decimal — porción que fue capital
└── note           CharField(255)

PawnRenewal (Renovación)
├── public_id          UUID unique
├── contract           FK → PawnContract
├── cash_session       FK → CashSession
├── renewed_by         FK → User
├── renewed_at         DateTimeField auto
├── previous_due_date  DateField
├── new_due_date       DateField
├── amount_charged     Decimal — total cobrado (interés + comisión)
├── interest_charged   Decimal
├── fee_charged        Decimal
└── note               CharField(255)

PawnAmortization (Adenda de Amortización)
├── public_id           UUID unique
├── contract            FK → PawnContract
├── cash_session        FK → CashSession
├── performed_by        FK → User
├── performed_at        DateTimeField auto
├── outstanding_before  Decimal — capital antes de la adenda
├── capital_paid        Decimal — abono a capital
├── interest_paid       Decimal — interés cobrado en esta adenda
├── previous_due_date   DateField — igual que new_due_date (fecha NO cambia)
├── new_due_date        DateField — igual que previous_due_date
└── note                CharField(255)
```

**Estados del Contrato y Transiciones:**

```
ACTIVE
  ├── today < due_date                    → ACTIVO (puede amortizar)
  ├── due_date ≤ today ≤ due_date+gracia  → VENCIDO (interés congelado a due_date)
  ├── today > due_date+gracia             → EN_MORA
  │     └── días sin actividad > 90       → ELEGIBLE_VENTA
  └── manual EN_VENTA                     → EN_VENTA
        └── venta completada              → SOLD
CLOSED    ← pago total (capital + interés)
CANCELLED ← cancelado manualmente
DEFAULTED ← marcado por proceso automático (process-defaults)
```

---

### 4.3 Clientes y Scoring

```
Customer (Cliente)
├── public_id          UUID unique
├── ci                 CharField(30) UNIQUE DB_INDEX — Cédula de Identidad
├── first_name         CharField(80)
├── last_name_paternal CharField(80)
├── last_name_maternal CharField(80) blank
├── birth_date         DateField
├── photo_face         ImageField  customers/faces/%Y/%m/
├── photo_ci           ImageField  customers/ci_docs/%Y/%m/
├── phone              CharField(20) — formato +591XXXXXXXX
├── email              EmailField blank
├── address / gps_lat / gps_lon  TextField / Decimal null
├── is_blacklisted     BooleanField
├── blacklist_reason   TextField
├── category           BRONCE | PLATA | ORO  default=BRONCE
├── custom_rate_pct    Decimal null — tasa mensual personalizada (anula categoría)
├── score              IntegerField 0-100 default=50
├── total_contracts    PositiveInt denormalized
├── late_payments_count / on_time_payments_count  PositiveInt
├── created_by         FK → User
└── created_at / updated_at  DateTimeField

    PROPERTIES:
    full_name   → "{first} {paternal} {maternal}"
    risk_color  → GREEN(≥70) | YELLOW(40-69) | RED(<40)
    age         → años calculados desde birth_date

CustomerReference (Referencia personal)
├── customer      FK → Customer (CASCADE)
├── full_name     CharField(120)
├── phone         CharField(20)
└── relationship  CharField(60)
```

**Reglas de Scoring:**

| Evento | Puntos |
|---|---|
| Pago puntual (≤ due_date) | +10 |
| Pago tardío | -5/día (cap -30) |
| Contrato en mora (DEFAULTED) | -20 base + -2/día (cap -50) |
| Recategorización | ORO ≥ 80 · PLATA ≥ 50 · BRONCE < 50 |

---

### 4.4 Inversionistas

```
Investor
├── public_id       UUID unique
├── full_name       CharField(255)
├── ci              CharField(50) blank
├── profit_rate_pct Decimal default=50.00 — % de utilidad que le corresponde
└── created_at      DateTimeField auto

InvestorAccount (Saldo disponible)
└── investor  OneToOne → Investor
└── balance   Decimal default=0

InvestorMovement (Movimientos del inversionista)
├── investor          FK → Investor
├── amount            Decimal
├── movement_type     DEPOSIT | ASSIGN | RETURN | PROFIT | WITHDRAW
├── related_contract  FK → PawnContract null
├── created_at        DateTimeField auto
└── note              CharField(255)
```

**Ciclo del Inversionista:**
```
DEPOSIT → fondea su cuenta (InvestorAccount.balance ++)
ASSIGN  → se asigna a un contrato (balance --)
RETURN  → contrato cancelado (balance ++)
PROFIT  → se le paga su parte de utilidad
WITHDRAW → retira su capital
```

---

### 4.5 Transferencias entre Cajas

```
Transfer
├── public_id          UUID unique
├── from_cash_register FK → CashRegister
├── to_cash_register   FK → CashRegister
├── amount             Decimal
├── status             PENDING | COMPLETED | REJECTED
├── created_by         FK → User
├── accepted_by        FK → User null
├── created_at         DateTimeField auto
├── accepted_at        DateTimeField null
└── note               CharField(255)
```

---

### 4.6 Inventario — Compra Directa

```
DirectPurchase (Compra Directa / CD)
├── public_id            UUID unique
├── branch               FK → Branch
├── status               COMPRADO_PENDIENTE | EN_VENTA | VENDIDO | CANCELADO
├── cash_session         FK → CashSession
├── created_by           FK → User
├── created_at           DateTimeField auto
├── category             LAPTOP | PHONE | JEWELRY | APPLIANCE | CONSOLE | INSTRUMENT | OTHER
├── description          TextField
├── attributes           JSONField
├── market_value_estimate Decimal null
├── purchase_price       Decimal
├── pvp                  Decimal null — precio de venta en vitrina
├── projected_profit     Decimal null
├── priced_by / priced_at FK User / DateTimeField null
├── qr_code_data         CharField null
├── sale_cash_session    FK → CashSession null
├── sold_by / sold_at    FK User / DateTimeField null
├── sale_price           Decimal null
└── actual_profit        Decimal null

DirectPurchasePhoto
├── public_id    UUID unique
├── purchase     FK → DirectPurchase
├── photo        FileField  inventory/photos/%Y/%m/
├── uploaded_at  DateTimeField auto
└── uploaded_by  FK → User
```

---

### 4.7 MVI — Motor de Valoración Inteligente

```
MVIConfig (Singleton pk=1)
├── gold_price_24k_gram_bs     Decimal default=580.00
├── silver_price_gram_bs       Decimal default=7.50
├── depreciation_phone_pct     Decimal default=4.50  % mensual compuesto
├── depreciation_laptop_pct    Decimal default=3.50
├── depreciation_console_pct   Decimal default=2.50
├── depreciation_appliance_pct Decimal default=1.50
├── depreciation_other_pct     Decimal default=2.00
├── loan_to_value_pct          Decimal default=60.00  % del valor intrínseco
├── vip_bonus_pct              Decimal default=15.00  bonus para clientes ORO
├── soft_warning_pct           Decimal default=15.00  aviso al superar recomendado
├── hard_block_pct             Decimal default=30.00  bloqueo — requiere override
├── updated_at                 DateTimeField auto
└── updated_by                 FK → User null

AppraisalOverride (Override de Tasación)
├── public_id            UUID unique
├── contract             OneToOne → PawnContract null — vinculado al crear el contrato
├── branch               FK → Branch
├── category             CharField(20)
├── description          TextField
├── condition            CharField(20) default=GOOD
├── customer_ci          CharField blank
├── system_recommendation  Decimal — lo que el MVI recomendó
├── system_max_allowed     Decimal — límite MVI
├── principal_requested    Decimal — lo que el cajero solicitó
├── override_reason        TextField
├── requested_by           FK → User
├── requested_at           DateTimeField auto
├── authorized_by          FK → User null
├── authorized_at          DateTimeField null
├── authorization_note     TextField blank
└── status                 PENDING | APPROVED | DENIED  default=PENDING
```

---

### 4.8 Tasas de Interés Configurables

```
InterestCategoryConfig (Configura tasas por categoría desde BD)
├── category       BRONCE | PLATA | ORO  UNIQUE
├── base_rate_pct  Decimal  — tasa mensual base (%)
├── max_principal  Decimal  — capital máximo prestable (Bs.)
├── updated_by     FK → User
└── updated_at     DateTimeField auto
```

> Si no existe fila en BD, el sistema usa los defaults hardcoded en `credit_line_calc.py`.

---

### 4.9 Mensajería WhatsApp

```
WhatsAppMessage (Cola de mensajes)
├── public_id     UUID unique
├── customer      FK → Customer
├── contract      FK → PawnContract null
├── event_type    DUE_REMINDER | OVERDUE_NOTICE | PAYMENT_CONFIRM | WELCOME
├── status        PENDING | SENT | DELIVERED | READ | FAILED
├── phone_to      CharField(20) — snapshot del número al encolar
├── message_body  TextField
├── scheduled_for DateTimeField
├── sent_at       DateTimeField null
├── wa_message_id CharField(100) blank
├── error_log     TextField blank
└── created_at    DateTimeField auto
    INDEX: (status, scheduled_for)
```

---

### 4.10 RRHH

```
HRConfig (Singleton pk=1)
├── smn                      Decimal default=2362.00 — Salario Mínimo Nacional Bolivia 2024
├── afp_rate_pct             Decimal default=12.71   — AFP/Gestora Pública (%)
├── night_surcharge_start_hour PositiveSmallInt default=20
├── night_surcharge_pct      Decimal default=25.00
└── updated_by / updated_at  FK User / DateTimeField auto

Employee (Empleado)
├── public_id          UUID unique
├── user               OneToOne → auth.User
├── branch             FK → Branch
├── cash_register      FK → CashRegister null
├── first/last names + ci + complemento_ci + nua_cua + phone + address
├── contract_type      INDEFINIDO | PLAZO_FIJO | EVENTUAL
├── work_schedule      FULL_TIME(48h) | HALF_TIME(24h)
├── hire_date          DateField
├── trial_end_date     DateField null
├── base_salary        Decimal
├── status             ACTIVE | ON_VACATION | SUSPENDED | TERMINATED
├── contract_file / ci_scan / domicile_sketch  FileField null
└── created_by / created_at / updated_at

    PROPERTIES:
    full_name        → "{first} {paternal} {maternal}"
    seniority_years  → años completos desde hire_date
    seniority_months → meses completos desde hire_date
    has_afp          → bool(nua_cua)
    weekly_hours     → 48 | 24
    daily_hours      → 8 | 4

SalaryScale (Escalera salarial)
├── employee      FK → Employee (CASCADE)
├── month_number  PositiveSmallInt
├── salary        Decimal
└── note          CharField(255)
    UNIQUE: (employee, month_number)

AttendanceRecord (Asistencia)
├── employee         FK → Employee
├── date             DateField
├── clock_in         DateTimeField
├── clock_out        DateTimeField null
├── ip_address       GenericIPAddressField null
├── regular_hours / overtime_hours / night_hours  Decimal
└── note             CharField(255)
    UNIQUE: (employee, date)

SalaryPeriod (Planilla mensual)
├── employee / year / month   — UNIQUE(employee, year, month)
├── base_salary / days_worked
├── overtime_hours / overtime_amount
├── night_surcharge_hours / night_surcharge_amount
├── seniority_years / seniority_pct / seniority_bonus_base / seniority_bonus_amount
├── performance_bonus / performance_bonus_note
├── cash_shortage_deduction / cash_shortage_note
├── other_deductions / other_deductions_note
├── afp_deduction_pct / afp_deduction_amount
├── total_gross / total_deductions / net_salary
├── status   DRAFT | APPROVED | PAID
└── approved_by / approved_at / paid_at

VacationPeriod (Vacaciones)
├── employee / accrual_year     — UNIQUE(employee, accrual_year)
├── calendar_year / days_available / days_taken
├── start_date / end_date
├── status   ACCRUING | AVAILABLE | SCHEDULED | TAKEN
└── approved_by / approved_at / notes

EmployeeTermination (Liquidación)
├── employee          OneToOne → Employee
├── termination_date  DateField
├── reason            VOLUNTARY | EMPLOYER | MUTUAL | JUSTIFIED
├── months_worked / base_salary_snapshot
├── indemnization_months / indemnization_amount
├── aguinaldo_months / aguinaldo_amount
├── unused_vacation_days / unused_vacation_amount
├── total_liquidation Decimal
└── notes / created_by / created_at

AguinaldoPeriod (Aguinaldo)
├── employee / year / aguinaldo_type    — UNIQUE(employee, year, type)
├── aguinaldo_type  REGULAR | DOBLE
├── hire_date_snapshot / base_salary_snapshot
├── months_in_period / days_worked_in_year / qualifies
├── amount
├── status   DRAFT | APPROVED | PAID
└── approved_by / approved_at / paid_at
```

---

### 4.11 Seguridad y Acceso

```
Role
├── code  CharField UNIQUE  — CAJERO | SUPERVISOR | OWNER_ADMIN | AUDITOR
└── name  CharField(60)

UserRole
├── user  FK → auth.User
└── role  FK → Role
    UNIQUE: (user, role)

UserBranchAccess
├── user    FK → auth.User
└── branch  FK → Branch
    UNIQUE: (user, branch)
```

---

### 4.12 Denominaciones de Billetes

```
CashDenomination (Conteo físico en apertura/cierre)
├── cash_session  FK → CashSession
├── denom_type    OPENING | CLOSING
├── b_200 / b_100 / b_50 / b_20 / b_10   PositiveInt — billetes
├── c_5 / c_2 / c_1                       PositiveInt — monedas
├── counted_by    FK → User
└── created_at    DateTimeField auto
```

---

## 5. SERVICIOS Y LÓGICA DE NEGOCIO

### 5.1 `interest_calc.py` — Cálculo de Interés Prorateado

```python
prorated_interest(principal, monthly_rate_percent, from_date, to_date) → Decimal
# Fórmula: principal × (monthly_rate / 100) × (days / 30)
# days = (to_date - from_date).days
```

### 5.2 `interest_policy.py` — Política de Tasa por Monto

```python
interest_rate_monthly_for_principal(principal) → Decimal
# < 1500 Bs     → 10.00%
# 1500–8000 Bs  →  8.00%
# > 8000 Bs     →  7.00%
```

### 5.3 `credit_line_calc.py` — Línea de Crédito y Tasa Aplicable

**Jerarquía de tasa (mayor prioridad primero):**
1. `customer.custom_rate_pct` — tasa individual configurada manualmente
2. `InterestCategoryConfig[category].base_rate_pct` — config en BD por categoría
3. Defaults hardcoded en `CATEGORY_CONFIG`

```python
CATEGORY_CONFIG = {
    "BRONCE": {"base_rate": 10.00, "max_principal": 1500.00},
    "PLATA":  {"base_rate":  8.00, "max_principal": 8000.00},
    "ORO":    {"base_rate":  7.00, "max_principal": 20000.00},
}
ORO_RATE_DISCOUNT = 0.50%   # descuento adicional para ORO
MIN_ALLOWED_RATE  = 5.00%   # tasa mínima absoluta

# Factor de score: 0.5 + (score/100) * 0.5
# score=50 → factor=0.75 → max_amount = 75% del límite de categoría
# score=100 → factor=1.00 → max_amount = 100% del límite
```

### 5.4 `contract_state.py` — Máquina de Estados

```python
ContractState = {
    ACTIVO, VENCIDO, EN_MORA, ELEGIBLE_VENTA, EN_VENTA, VENDIDO, CERRADO, CANCELADO
}

get_contract_state(contract, today=None) → str
# Usa Branch.grace_period_days (no hardcoded)
# Gracia: due_date ≤ today ≤ due_date + grace → VENCIDO (interés congelado)
# > gracia y días sin actividad → EN_MORA
# Sin actividad 90+ días → ELEGIBLE_VENTA

calculate_recovery_amount(contract, today=None) → dict
# Retorna: state, outstanding_principal, interest_due, total_to_recover,
#          can_amortize (solo ACTIVO), can_recover (ACTIVO | VENCIDO | EN_MORA)
```

### 5.5 `pawn_amortization.py` — Amortizaciones

```
REGLAS DE NEGOCIO:
- Solo contratos en estado ACTIVO (today < due_date) pueden amortizar
- La due_date NO cambia al amortizar (se preserva la fecha original del contrato)
- Se crea PawnPayment + PawnAmortization + CashMovement (PAYMENT_IN)
- Se actualiza interest_accrued_until = hoy

CIERRE DE CONTRATO CON AMORTIZACIONES (en pawn_payment.py):
- Si contract.amortizations.exists():
    interés_cierre = principal_amount × interest_rate_monthly / 100
    (Interés fijo del primer mes, no prorateado)
- Si NO hay amortizaciones:
    interés_cierre = prorated_interest(outstanding, rate, from_date, payment_date)
```

### 5.6 `mvi_engine.py` — Motor de Valoración Inteligente

```
JOYAS (JEWELRY):
  valor_intrínseco = weight_grams × pureza_karat × metal_price_gram
  pureza karat: 8k=0.333, 9k=0.375, 10k=0.417, 12k=0.500,
                14k=0.583, 18k=0.750, 20k=0.833, 22k=0.916, 24k=0.999

TECH (PHONE, LAPTOP, CONSOLE, APPLIANCE):
  valor_depreciado = market_value × (1 - tasa_mensual)^meses_transcurridos

FACTORES DE CONDICIÓN:
  EXCELLENT: × 1.10
  GOOD:      × 1.00
  WORN:      × 0.75
  DAMAGED:   × 0.50

PRÉSTAMO SUGERIDO:
  recomendado    = valor × LTV(60%) × condición
  max_soft       = recomendado × (1 + soft_warning_pct/100)  → alerta
  hard_max       = recomendado × (1 + hard_block_pct/100)    → bloquea
  vip_max (ORO)  = recomendado × (1 + vip_bonus_pct/100)

MULTI-ARTÍCULO: suma de recomendados de todos los items
```

### 5.7 `scoring_engine.py` — Motor de Scoring

```python
apply_contract_closure_score(contract)  # al cerrar un contrato
# días_tarde = max(0, days(paid_at - due_date))
# si puntual: +10
# si tarde:   -5/día (cap -30)
# aplica_recategorización si cambia el umbral

apply_default_penalty(contract)  # al marcar como DEFAULTED
# días_vencido = today - due_date
# penalización = min(50, 20 + 2 × días_vencido)

increment_contract_count(customer)  # al crear un contrato
# customer.total_contracts += 1 (atómico)
```

### 5.8 `cash_alerts.py` — Alertas y Balance de Caja

```
expected_balance (CashSession property):
  Si CLOSED → retorna closing_expected_amount (valor guardado)
  Si OPEN   → opening_amount + Σ(movements._IN) - Σ(movements._OUT)

calculate_surplus(session):
  net_surplus = expected_balance - opening_amount - capital_in + capital_out
  (excluye movimientos de capital del dueño del cálculo de utilidad operativa)

validate_opening_vs_previous(opening_amount, register):
  Compara con closing_counted_amount de la última sesión CLOSED
```

### 5.9 `hr_calculator.py` — Cálculos RRHH (Ley Boliviana)

```
BONO DE ANTIGÜEDAD (DS 1213):
  Base = 3 × SMN
  Escala: 25y→50%, 20y→42%, 15y→34%, 11y→26%, 8y→18%, 5y→11%, 2y→5%

AFP/GESTORA:  12.71% del salario bruto (configurable en HRConfig)
HORAS EXTRA:  > daily_hours (8 | 4)
RECARGO NOCTURNO: horas después de las 20:00 → +25%
HORA BASE: base_salary / (26 días × daily_hours)

VACACIONES (LGT Art. 55):
  1-4 años → 15 días | 5-9 años → 20 días | 10+ años → 30 días

AGUINALDO (DS 110 / DS 1802):
  Período: 1 enero – 30 noviembre (máx 11 meses)
  Requisito: ≥ 90 días trabajados
  Monto = base_salary × meses_en_período / 12
  Plazo de pago: 20 de diciembre

INDEMNIZACIÓN (solo EMPLOYER o MUTUAL):
  1 mes de sueldo por año trabajado (proporcional si < 1 año)
```

---

## 6. API — ENDPOINTS COMPLETOS

Todos los endpoints bajo el prefijo `/api/`. Autenticación: `Authorization: Bearer <jwt_token>`

### 6.1 Autenticación

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/auth/me` | Perfil del usuario autenticado |

### 6.2 Gestión de Cajas

| Método | Ruta | Descripción | Rol |
|---|---|---|---|
| GET | `/cash-registers` | Listar cajas | ANY |
| GET | `/cash-registers/balances` | Saldos de todas las cajas | ANY |
| GET | `/cash-registers/alerts` | Alertas de umbral por caja | ANY |
| GET/POST | `/cash-registers/<uuid>/capital` | Inyectar capital (CAPITAL_IN) | OWNER |
| POST | `/cash-registers/<uuid>/capital/withdraw` | Retirar capital (CAPITAL_OUT) | OWNER |
| GET | `/cash-registers/<uuid>/capital/history` | Historial de capital | OWNER |
| GET/PATCH | `/cash-registers/<uuid>/settings` | Config de la caja | OWNER |
| POST | `/cash-sessions/open` | Abrir sesión | ANY |
| POST | `/cash-sessions/close` | Cerrar sesión | ANY |
| POST | `/cash-sessions/reopen` | Reabrir sesión | SUPERVISOR+ |
| GET | `/cash-sessions/current` | Sesión activa del usuario | ANY |
| GET | `/cash-sessions/<uuid>/summary` | Resumen de la sesión | ANY |
| GET | `/cash-sessions/<uuid>/balance` | Saldo actual | ANY |
| GET | `/cash-sessions/<uuid>/movements` | Movimientos de la sesión | ANY |
| GET | `/cash-sessions/<uuid>/closing-report.pdf` | PDF de cierre | ANY |
| GET/POST | `/cash-sessions/<uuid>/denomination` | Denominaciones (billetes) | ANY |
| GET/POST | `/cash-sessions/<uuid>/expenses` | Gastos operativos | ANY |
| GET/POST | `/cash-sessions/<uuid>/purchases` | Compras directas | ANY |
| GET | `/dashboard/cash` | Dashboard de caja | ANY |
| POST | `/transfers` | Crear transferencia entre cajas | SUPERVISOR+ |
| POST | `/transfers/<uuid>/accept` | Aceptar transferencia | SUPERVISOR+ |

**Respuesta de cierre de sesión (`POST /cash-sessions/close`):**
```json
{
  "session":      { "cash_session_id", "register_name", "branch_code", "opened_by", "closed_by", "opened_at", "closed_at" },
  "amounts":      { "opening_amount", "expected_amount", "counted_amount", "difference", "difference_label" },
  "next_opening": { "reference_amount", "message", "min_balance", "max_balance", "below_minimum" },
  "surplus_breakdown": { "net_surplus", "profit_earned", "capital_recovered", "loan_out", ... },
  "report_url"
}
```

### 6.3 Contratos de Empeño

| Método | Ruta | Descripción | Rol |
|---|---|---|---|
| POST | `/pawn-contracts` | Crear contrato | CAJERO+ |
| GET | `/pawn-contracts/list` | Listar contratos | ANY |
| GET | `/pawn-contracts/<uuid>` | Detalle de contrato | ANY |
| GET | `/pawn-contracts/<uuid>/state` | Estado en tiempo real | ANY |
| GET | `/pawn-contracts/<uuid>/amortize/preview?capital=X` | Preview amortización | ANY |
| POST | `/pawn-contracts/<uuid>/amortize` | Ejecutar amortización | CAJERO+ |
| POST | `/pawn-contracts/payments` | Cobrar / cerrar contrato | CAJERO+ |
| POST | `/pawn-contracts/renew` | Renovar contrato | CAJERO+ |
| POST | `/pawn-contracts/cancel` | Cancelar contrato | SUPERVISOR+ |
| GET | `/pawn-contracts/defaulted` | Contratos en mora | ANY |
| POST | `/pawn-contracts/process-defaults` | Procesar moras automáticamente | OWNER |

> **Multi-sucursal:** Pagos, renovaciones y amortizaciones pueden realizarse desde CUALQUIER caja de CUALQUIER sucursal. No hay restricción de mismo-sucursal.

**Crear contrato — body:**
```json
{
  "cash_session_id": "uuid",
  "customer_full_name": "...",
  "customer_ci": "1234567",
  "principal_amount": 1000.00,
  "interest_mode": "FIXED",
  "items": [
    {
      "category": "PHONE",
      "description": "Samsung Galaxy S23",
      "condition": "GOOD",
      "attributes": {"marca": "Samsung", "modelo": "S23"},
      "loan_amount": 500.00
    }
  ]
}
```

### 6.4 Inventario (Compra Directa)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/inventory` | Listar artículos en vitrina |
| POST | `/inventory/direct-purchase` | Registrar compra directa |
| GET | `/inventory/<uuid>` | Detalle del artículo |
| POST | `/inventory/<uuid>/photos` | Subir fotos |
| GET/POST | `/inventory/<uuid>/price` | Establecer precio de venta |
| GET | `/inventory/<uuid>/qr` | Código QR |
| POST | `/inventory/<uuid>/sell` | Registrar venta |
| POST | `/inventory/<uuid>/cancel` | Cancelar compra |

### 6.5 Clientes

| Método | Ruta | Descripción |
|---|---|---|
| GET/POST | `/customers` | Listar / crear cliente |
| GET | `/customers/<ci>` | Detalle del cliente |
| GET | `/customers/<ci>/dashboard` | Panel completo del cliente |
| POST | `/customers/<ci>/photos` | Subir foto facial / CI |
| GET | `/customers/<ci>/whatsapp` | Historial de mensajes |
| GET/PATCH | `/customers/<ci>/rate` | Ver / cambiar tasa personalizada |

### 6.6 WhatsApp

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/whatsapp/queue-reminders` | Encolar recordatorios de vencimiento |
| POST | `/whatsapp/queue-overdue` | Encolar avisos de mora |
| GET | `/whatsapp/pending` | Ver cola pendiente |
| POST | `/whatsapp/<uuid>/mark-sent` | Marcar como enviado |

### 6.7 MVI — Motor de Valoración

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/mvi/suggest` | Obtener sugerencia de préstamo |
| GET/POST | `/mvi/config` | Ver / actualizar configuración MVI |
| GET | `/mvi/overrides` | Listar solicitudes de override |
| POST | `/mvi/overrides/create` | Crear solicitud de override |
| GET | `/mvi/overrides/pending-alert` | Alerta de overrides pendientes |
| POST | `/mvi/overrides/whatsapp-alert` | Enviar alerta WhatsApp |
| POST | `/mvi/overrides/<uuid>/authorize` | Autorizar override (OWNER) |
| POST | `/mvi/overrides/<uuid>/deny` | Denegar override (OWNER) |

### 6.8 Panel del Dueño

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/dashboard/owner` | Dashboard ejecutivo |
| GET | `/owner/treasury` | Posición de capital en tiempo real |
| GET | `/owner/profitability?from=&to=&branch=` | P&L del período |
| GET | `/owner/investors` | Lista de inversionistas |
| GET | `/owner/investors/<uuid>/statement` | Estado de cuenta del inversionista |
| POST | `/owner/investors/<uuid>/deposit` | Registrar depósito del inversionista |
| POST | `/owner/investors/<uuid>/profit` | Pagar utilidades al inversionista |
| POST | `/owner/investors/<uuid>/withdraw` | Retirar capital del inversionista |

### 6.9 Configuración de Tasas

| Método | Ruta | Descripción | Rol |
|---|---|---|---|
| GET | `/interest-rates/categories` | Ver tasas por categoría | ANY |
| PUT | `/interest-rates/categories` | Actualizar tasas por categoría | OWNER |
| GET | `/customers/<ci>/rate` | Tasa actual del cliente | ANY |
| PATCH | `/customers/<ci>/rate` | Establecer tasa personalizada | OWNER/CAJERO |

### 6.10 Gestión de Sucursales y Cajas (OWNER_ADMIN exclusivo)

| Método | Ruta | Descripción |
|---|---|---|
| GET/POST | `/branches` | Listar / crear sucursal |
| GET/PATCH | `/branches/<id>` | Ver / editar sucursal |
| POST | `/branches/<id>/cash-registers` | Crear caja en sucursal |
| GET/PATCH | `/cash-registers/<uuid>/settings` | Ver / editar config de caja |

### 6.11 RRHH

| Módulo | Endpoints |
|---|---|
| Configuración | `GET/POST /hr/config` |
| Empleados | `GET/POST /hr/employees` · `GET/PATCH /hr/employees/<uuid>` |
| Documentos | `POST /hr/employees/<uuid>/documents` |
| Asistencia | `POST /hr/attendance/clock-in` · `POST /clock-out` · `GET /hr/attendance` |
| Asistencia empleado | `GET /hr/employees/<uuid>/attendance` |
| Planilla | `POST /hr/payroll/generate` · `GET /hr/payroll` · `GET /hr/payroll/<year>/<month>` · `GET /hr/payroll/<id>` |
| Vacaciones | `GET/PUT /hr/vacations/<id>` · `GET /hr/employees/<uuid>/vacations` |
| Aguinaldo | `POST /hr/aguinaldo/generate` · `GET /hr/aguinaldo/<year>` · `GET /hr/aguinaldo/<year>/preview` · `GET /hr/aguinaldo/detail/<id>` · `GET /hr/employees/<uuid>/aguinaldos` |
| Baja | `POST /hr/employees/<uuid>/terminate` · `GET /hr/employees/<uuid>/audit-log` |

### 6.12 Reportes

| Ruta | Descripción |
|---|---|
| `GET /reports/daily-summary` | Resumen diario (JSON) |
| `GET /reports/daily-summary.pdf` | Resumen diario (PDF) |
| `GET /reports/risk-concentration` | Concentración de riesgo por sucursal |
| `GET /reports/default-summary` | Resumen de mora |
| `GET /reports/vitrina` | Artículos en vitrina / mora |
| `GET /reports/mvi/overrides` | Reporte de overrides MVI |
| `GET /reports/mvi/stats` | Estadísticas MVI |
| `GET /reports/hr/aguinaldo/<year>` | Reporte aguinaldo |
| `GET /reports/hr/payroll/<year>/<month>` | Reporte planilla |
| `GET /reports/hr/attendance/<year>/<month>` | Reporte asistencia |
| `GET /reports/hr/employees` | Directorio de empleados |

### 6.13 Usuarios y Meta

| Método | Ruta | Descripción |
|---|---|---|
| GET/POST | `/users` | Gestión de usuarios |
| GET/PUT | `/users/<id>` | Detalle de usuario |
| GET | `/meta/roles` | Roles disponibles |
| GET | `/meta/branches` | Sucursales activas |
| POST/GET | `/investor` `/investors` | Crear/listar inversionistas |
| GET | `/investors/<uuid>/account` | Cuenta del inversionista |

---

## 7. RBAC — ROLES Y PERMISOS

| Rol | Código | Capacidades |
|---|---|---|
| Cajero | `CAJERO` | Abrir/cerrar sesión, crear contratos, cobros, renovaciones, amortizaciones (cualquier sucursal), cambiar tasa de cliente |
| Supervisor | `SUPERVISOR` | Todo lo de CAJERO + cancelar contratos, reabrir sesiones, transferencias |
| Dueño Admin | `OWNER_ADMIN` | Acceso total: panel financiero, gestión de sucursales/cajas, configuración de tasas, inversionistas, RRHH completo, overrides MVI |
| Auditor | `AUDITOR` | Solo lectura |

**Acceso multi-sucursal (operativo):**
- `UserBranchAccess` define a qué sucursales tiene acceso un usuario
- OWNER_ADMIN tiene acceso implícito a todas
- Para pagos/renovaciones/amortizaciones: cualquier cajero con sesión abierta puede operar contratos de cualquier sucursal

---

## 8. FLUJOS OPERATIVOS CLAVE

### 8.1 Flujo Completo de un Empeño

```
1. CAJERO abre sesión de caja
   POST /cash-sessions/open  { cash_register_id, opening_amount }
   → Compara apertura con cierre_counted del día anterior (alerta si difiere)

2. CLIENTE llega a empeñar
   a. Buscar/crear cliente: POST /customers  { ci, nombre, teléfono, ... }
   b. Obtener sugerencia MVI: POST /mvi/suggest  { category, condition, attributes }
   c. Si monto > hard_max → crear override: POST /mvi/overrides/create
      → OWNER autoriza: POST /mvi/overrides/<uuid>/authorize
   d. Crear contrato: POST /pawn-contracts  { cash_session_id, customer_ci,
                                              principal_amount, items: [{loan_amount}] }
   → Genera CashMovement LOAN_OUT
   → Incrementa customer.total_contracts
   → Si investor_id: descuenta InvestorAccount.balance

3. Operaciones durante el período
   a. Renovar: POST /pawn-contracts/renew
      → Cobra interés prorateado, cobra comisión opcional, actualiza due_date
   b. Amortizar: POST /pawn-contracts/<uuid>/amortize  { capital_to_pay }
      → Cobra interés acumulado + abono al capital
      → due_date NO cambia
   c. Cobrar/cerrar: POST /pawn-contracts/payments  { amount }
      → Si amortizaciones previas: interés = principal_original × tasa
      → Si sin amortizaciones: interés prorateado hasta hoy
      → Si amount ≥ outstanding + interest → CLOSED + scoring

4. CAJERO cierra sesión
   POST /cash-sessions/close  { cash_session_id, counted_amount }
   → Guarda closing_expected_amount (saldo lógico)
   → Guarda closing_counted_amount (conteo físico)
   → Si diff ≠ 0 → ADJUSTMENT_IN/OUT automático
   → Respuesta incluye next_opening.reference_amount para el día siguiente
```

### 8.2 Flujo de Mora Automática

```
Cron / management command:
  POST /pawn-contracts/process-defaults
  → Para cada contrato ACTIVE con today > due_date + branch.grace_period_days:
      1. contract.status = DEFAULTED
      2. apply_default_penalty(contract) → score penalty
      3. Encolar WhatsApp OVERDUE_NOTICE
```

### 8.3 Flujo del Inversionista

```
OWNER_ADMIN:
  POST /owner/investors/<uuid>/deposit  { amount, register_id }
  → InvestorMovement DEPOSIT  |  InvestorAccount.balance += amount
  → CashMovement CAPITAL_IN (opcional)

  Al crear contrato con investor_id:
  → InvestorMovement ASSIGN  |  InvestorAccount.balance -= principal
  → contract.investor = investor

  Si contrato cancelado:
  → InvestorMovement RETURN  |  InvestorAccount.balance += principal

  POST /owner/investors/<uuid>/profit  { amount }
  → InvestorMovement PROFIT  |  CashMovement CAPITAL_OUT

  POST /owner/investors/<uuid>/withdraw  { amount }
  → Valida balance suficiente
  → InvestorMovement WITHDRAW  |  CashMovement CAPITAL_OUT
```

### 8.4 Cálculo de Utilidad del Dueño (P&L)

```
UC  = intereses cobrados (PAYMENT_IN de pagos + renovaciones + amortizaciones)
UV  = margen ventas CD (sale_price - purchase_price de DirectPurchase VENDIDO)
G   = gastos operativos (EXPENSE_OUT)
UNI = utilidad inversionista = Σ(interés_por_contrato × profit_rate_pct/100)
UN  = UC + UV - G - UNI  ← utilidad neta del dueño

net_surplus de caja = expected_balance - opening_amount - CAPITAL_IN + CAPITAL_OUT
(excluye movimientos de capital del dueño para no inflar la utilidad operativa)
```

---

## 9. CONSTANTES Y PARÁMETROS DE NEGOCIO

### Tasas de Interés (defaults — sobreescribibles desde BD)

| Categoría | Tasa Mensual | Capital Máximo |
|---|---|---|
| BRONCE | 10.00% | Bs. 1,500 |
| PLATA | 8.00% | Bs. 8,000 |
| ORO | 7.00% (−0.5% descuento) | Bs. 20,000 |
| Mínimo absoluto | 5.00% | — |

### MVI — Depreciation & LTV

| Parámetro | Valor Default |
|---|---|
| Oro 24k | Bs. 580.00/g |
| Plata | Bs. 7.50/g |
| Depreciación Celular | 4.50%/mes |
| Depreciación Laptop | 3.50%/mes |
| Depreciación Consola | 2.50%/mes |
| Depreciación Electrodoméstico | 1.50%/mes |
| Depreciación Otros | 2.00%/mes |
| LTV (Loan-to-Value) | 60% del valor intrínseco |
| Bonus VIP (ORO) | +15% sobre recomendado |
| Soft Warning | +15% sobre recomendado |
| Hard Block | +30% sobre recomendado |

### Condición del Artículo

| Estado | Factor |
|---|---|
| EXCELLENT | × 1.10 |
| GOOD | × 1.00 |
| WORN | × 0.75 |
| DAMAGED | × 0.50 |

### Pureza del Oro (Karat)

| Karat | Pureza |
|---|---|
| 8k | 0.333 | 10k | 0.417 | 14k | 0.583 | 18k | 0.750 | 22k | 0.916 |
| 9k | 0.375 | 12k | 0.500 | 20k | 0.833 | 24k | 0.999 |

### Caja — Umbrales Operativos (por CashRegister)

| Parámetro | Default | Configuración |
|---|---|---|
| Saldo mínimo | Bs. 1,000 | `CashRegister.min_balance` |
| Saldo máximo | Bs. 4,000 | `CashRegister.max_balance` |
| Días de gracia | 30 días | `Branch.grace_period_days` |

### RRHH — Constantes Legales Bolivia

| Parámetro | Valor |
|---|---|
| SMN 2024 | Bs. 2,362.00 |
| AFP / Gestora | 12.71% |
| Recargo nocturno | 25% (desde las 20:00) |
| Vacaciones 1-4 años | 15 días |
| Vacaciones 5-9 años | 20 días |
| Vacaciones 10+ años | 30 días |
| Aguinaldo plazo | 20 de diciembre |
| Aguinaldo mínimo | 90 días trabajados |

---

## 10. HISTORIAL DE MIGRACIONES

| # | Nombre | Contenido |
|---|---|---|
| 0001 | initial | Branch, CashRegister, CashSession, CashMovement inicial |
| 0002 | role_userbranchaccess_userrole | Módulo seguridad RBAC |
| 0003 | cashregister/session public_id | UUIDs en cajas |
| 0004 | populate_cashregister_public_id | Datos de UUIDs |
| 0005 | enforce_public_id_unique | Constraints únicos |
| 0006 | cashmovement | Modelo CashMovement completo |
| 0007 | pawncontract | Contratos de empeño |
| 0008 | alter_cashmovement + branchcounter | Tipo movimiento + contador sucursal |
| 0009 | pawnpayment | Pagos de contratos |
| 0010 | pawnrenewal | Renovaciones |
| 0011 | pawncontract_interest_accrued_until | Campo de interés acumulado |
| 0012 | pawnitem | Artículos empeñados |
| 0013 | alter_pawnitem | Ajustes de artículos |
| 0014 | transfer | Transferencias entre cajas |
| 0015 | investor + investoraccount + investormovement | Módulo inversionistas |
| 0016 | pawncontract_investor | FK contrato → inversionista |
| 0017 | fix_loan_out_sign + customer | Corrección signos + módulo clientes |
| 0018 | cashflow_enhancements | CAPITAL_IN/OUT, panel dueño |
| 0019 | mora_module | Procesamiento automático de mora |
| 0020 | hr_module | RRHH completo (Employee, SalaryPeriod, etc.) |
| 0021 | aguinaldo | Módulo aguinaldo (DS 110 / DS 1802) |
| 0022 | contract_status_expand | Estados EN_VENTA y SOLD |
| 0023 | amortization_inventory | PawnAmortization + DirectPurchase |
| 0024 | mvi_condition | MVIConfig + AppraisalOverride + PawnItem.condition |
| 0025 | interest_config + customer_rate + loanamount | InterestCategoryConfig + Customer.custom_rate_pct + PawnItem.loan_amount |

---

## 11. INTEGRACIONES EXTERNAS

### Meta Cloud API (WhatsApp Business)
- **Endpoint:** `https://graph.facebook.com/{version}/{phone_id}/messages`
- **Autenticación:** Bearer Token (`WHATSAPP_TOKEN`)
- **Flujo:** Cola interna (`WhatsAppMessage`) → worker/management command → envío real
- **Horario operativo:** 08:00–18:00, sin fines de semana (configurable)
- **Delay humanizado:** 30–90 segundos entre mensajes

### JWT (Autenticación)
- `POST /api/token/` → obtener access + refresh
- `POST /api/token/refresh/` → renovar access token
- Header: `Authorization: Bearer <access_token>`

---

## APÉNDICE — Relaciones Principales (ERD simplificado)

```
auth.User
  ├── UserRole ──────────── Role
  ├── UserBranchAccess ──── Branch
  │                           ├── BranchCounter
  │                           ├── CashRegister(s)
  │                           │     └── CashSession(s)
  │                           │           └── CashMovement(s)
  │                           └── Employee(s)
  └── Employee (OneToOne)

Customer
  └── PawnContract(s) ─── PawnItem(s)
                      ├── PawnPayment(s)
                      ├── PawnRenewal(s)
                      ├── PawnAmortization(s)
                      └── AppraisalOverride (OneToOne)

Investor ── InvestorAccount
        └── InvestorMovement(s)
        └── PawnContract(s) (como financiador)
```
