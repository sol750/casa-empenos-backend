import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone


class Branch(models.Model):
    """
    Sucursal.
    """
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True)  # ej: PT1, PT2
    is_active = models.BooleanField(default=True)

    # Días de gracia antes de marcar un contrato como DEFAULTED
    grace_period_days = models.PositiveSmallIntegerField(
        default=30,
        help_text="Días hábiles de gracia tras el vencimiento antes de pasar a mora.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sucursal"
        verbose_name_plural = "Sucursales"

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
    

class BranchCounter(models.Model):
    """
    Contador por sucursal para numeración de contratos.
    Auditoría: evita duplicados y permite concurrencia.
    """
    branch = models.OneToOneField("Branch", on_delete=models.PROTECT, related_name="counter")
    pawn_contract_seq = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.branch.code}: {self.pawn_contract_seq}"


class CashRegister(models.Model):
    """
    Caja física/lógica.
      BRANCH → caja operativa de sucursal (C1, C2)
      VAULT  → bóveda de sucursal (CB) para resguardo de excedente
      GLOBAL → caja maestra del dueño / tesoro central
    """
    class RegisterType(models.TextChoices):
        BRANCH = "BRANCH", "Caja Sucursal"
        VAULT  = "VAULT",  "Bóveda"
        GLOBAL = "GLOBAL", "Global"
    
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    name = models.CharField(max_length=60)  # Caja 1, Caja 2, Caja Global
    register_type = models.CharField(
        max_length=10,
        choices=RegisterType.choices,
        default=RegisterType.BRANCH,
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cash_registers",
    )
    is_active = models.BooleanField(default=True)

    # Umbrales operativos (Bs.) — configurables por caja
    min_balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("1000.00"),
        help_text="Mínimo operativo. Si el saldo baja de aquí se genera alerta de fondeo.",
    )
    max_balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("4000.00"),
        help_text="Máximo operativo. Si el saldo sube de aquí se genera alerta de saturación.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Caja"
        verbose_name_plural = "Cajas"
        constraints = [
            # BRANCH y VAULT requieren sucursal; GLOBAL no
            models.CheckConstraint(
                check=(
                    Q(register_type="GLOBAL", branch__isnull=True)
                    | Q(register_type="BRANCH", branch__isnull=False)
                    | Q(register_type="VAULT",  branch__isnull=False)
                ),
                name="cashregister_branch_required_when_branch_type",
            )
        ]

    def __str__(self) -> str:
        if self.register_type == self.RegisterType.GLOBAL:
            return f"[GLOBAL] {self.name}"
        return f"[{self.branch.code}] {self.name}"


class CashSession(models.Model):
    """
    Sesión de caja: apertura -> operaciones -> cierre.
    """
    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        CLOSED = "CLOSED", "Cerrada"
    
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)


    cash_register = models.ForeignKey(CashRegister, on_delete=models.PROTECT, related_name="sessions")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="cash_sessions")

    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_sessions_opened")
    opened_at = models.DateTimeField(auto_now_add=True)
    opening_amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cash_sessions_closed",
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    closing_counted_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closing_expected_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closing_diff_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closing_notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Sesión de Caja"
        verbose_name_plural = "Sesiones de Caja"
        constraints = [
            # Una sola sesión OPEN por caja
            models.UniqueConstraint(
                fields=["cash_register"],
                condition=Q(status="OPEN"),
                name="unique_open_cash_session_per_register",
            )
        ]

    def __str__(self) -> str:
        return f"{self.cash_register} - {self.status} - {self.opened_at:%Y-%m-%d %H:%M}"
    @property
    def expected_balance(self):
        # Si la sesión ya fue cerrada, devolvemos el valor guardado en DB (inmutable)
        if self.closing_expected_amount is not None:
            return self.closing_expected_amount

        # Dos consultas simples: suma entradas y suma salidas
        # (más confiable que Case/When para evitar falsos ceros)
        total_in = (
            self.movements
            .filter(movement_type__endswith="_IN")
            .aggregate(t=Sum("amount"))["t"]
        ) or Decimal("0.00")

        total_out = (
            self.movements
            .filter(movement_type__endswith="_OUT")
            .aggregate(t=Sum("amount"))["t"]
        ) or Decimal("0.00")

        return self.opening_amount + total_in - total_out

    
class CashMovement(models.Model):
    """
    Movimiento de dinero asociado a una sesión de caja.
    Base para auditoría y cálculo de expected.
    """
    class MovementType(models.TextChoices):
        # ── Capital del dueño ────────────────────────────────────────
        CAPITAL_IN     = "CAPITAL_IN",     "Inyección de Capital"
        CAPITAL_OUT    = "CAPITAL_OUT",    "Retiro de Capital / Utilidad"
        # ── Operaciones de caja ──────────────────────────────────────
        TRANSFER_IN    = "TRANSFER_IN",    "Transferencia Entrante"
        TRANSFER_OUT   = "TRANSFER_OUT",   "Transferencia Saliente"
        ADJUSTMENT_IN  = "ADJUSTMENT_IN",  "Ajuste Sobrante"
        ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Ajuste Faltante"
        LOAN_OUT       = "LOAN_OUT",       "CN – Desembolso de Contrato"
        PAYMENT_IN     = "PAYMENT_IN",     "CC/UC – Cobro de Contrato"
        PURCHASE_OUT   = "PURCHASE_OUT",   "CD – Compra Directa"
        EXPENSE_OUT    = "EXPENSE_OUT",    "G – Gasto Operativo"
        VAULT_IN       = "VAULT_IN",       "Ingreso a Bóveda"
        VAULT_OUT      = "VAULT_OUT",      "Salida de Bóveda"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="movements")
    cash_register = models.ForeignKey(CashRegister, on_delete=models.PROTECT, related_name="movements")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="cash_movements")

    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_movements")
    performed_at = models.DateTimeField(auto_now_add=True)

    # Fecha efectiva del movimiento para caja retroactiva (Fase de Sincronización).
    # None = usar performed_at.date(). Se fija en start_date para contratos históricos.
    effective_date = models.DateField(
        null=True, blank=True,
        help_text="Fecha real del documento físico. Solo se usa en modo sincronización legado.",
    )

    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Movimiento de Caja"
        verbose_name_plural = "Movimientos de Caja"

    def __str__(self):
        return f"{self.movement_type} {self.amount} - {self.cash_register}"
   
    

 
class PawnContract(models.Model):
    """
    Contrato de empeño.
    Auditoría: guarda tasa/condiciones al momento de crear.
    """
    class Status(models.TextChoices):
        ACTIVE     = "ACTIVE",     "Activo"
        CLOSED     = "CLOSED",     "Cerrado"
        DEFAULTED  = "DEFAULTED",  "En mora"
        CANCELLED  = "CANCELLED",  "Cancelado"
        EN_VENTA   = "EN_VENTA",   "En Vitrina"
        SOLD       = "SOLD",       "Vendido"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    contract_number = models.CharField(max_length=30, unique=True)  # Ej: PT1-000001

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pawn_contracts")
    created_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    # Cliente normalizado (FK). Los campos de texto se mantienen por compatibilidad
    # con contratos anteriores a la implementación del módulo Cliente.
    customer = models.ForeignKey(
        "Customer",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    # Campos legacy (texto libre) — se rellenan automáticamente desde Customer al crear
    customer_full_name = models.CharField(max_length=120)
    customer_ci = models.CharField(max_length=30, blank=True, default="")

    # Préstamo
    principal_amount = models.DecimalField(max_digits=12, decimal_places=2)  # capital
    interest_rate_monthly = models.DecimalField(max_digits=6, decimal_places=2, default=8.00)  # 8% mensual
    start_date = models.DateField(default=timezone.now)
    due_date = models.DateField()  # fecha vencimiento

    # Modo de interés aplicado al contrato
    interest_mode = models.CharField(
        max_length=20,
        default="FIXED",
        help_text="FIXED (mensual fijo) / PROMO (condición especial)"
    )
    promo_note = models.CharField(max_length=255, blank=True, default="")

    # Caja / desembolso
    disbursed_cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="pawn_disbursements")

    # Mora automática
    defaulted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Fecha/hora en que el contrato fue marcado automáticamente como DEFAULTED.",
    )

    # ── Gastos adicionales (Phase de Sincronización / operativa) ─────────────
    admin_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Gastos administrativos cobrados al momento de crear el contrato.",
    )
    storage_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Gastos de almacenaje cobrados al momento de crear el contrato.",
    )

    # ── Trazabilidad de digitalización ───────────────────────────────────────
    # Código de la sucursal/operador que digitalizó el contrato en modo SYNC.
    # Ej: "Pt1" → el número de contrato quedará como "Pt1-107" en los libros.
    sync_operator_code = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Iniciales de la sucursal que digitalizó este contrato. Ej: Pt1",
    )

    def __str__(self):
        return self.contract_number

    interest_accrued_until = models.DateField(null=True, blank=True)

    investor = models.ForeignKey(
        "Investor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="contracts"
    )


class PawnPayment(models.Model):
    """
    Pago/abono a un contrato (amortización).
    Auditoría: guarda el detalle interés/capital.
    """
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    contract = models.ForeignKey(PawnContract, on_delete=models.PROTECT, related_name="payments")
    cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="pawn_payments")

    paid_at = models.DateTimeField(auto_now_add=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pawn_payments")

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    interest_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    principal_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    note = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"{self.contract.contract_number} payment {self.amount}"


class PawnRenewal(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    contract = models.ForeignKey(PawnContract, on_delete=models.PROTECT, related_name="renewals")
    cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="pawn_renewals")

    renewed_at = models.DateTimeField(auto_now_add=True)
    renewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pawn_renewals")

    previous_due_date = models.DateField()
    new_due_date = models.DateField()

    amount_charged = models.DecimalField(max_digits=12, decimal_places=2)
    interest_charged = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fee_charged = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    note = models.CharField(max_length=255, blank=True, default="")


class PawnItem(models.Model):
    class Category(models.TextChoices):
        LAPTOP = "LAPTOP", "Laptop"
        PHONE = "PHONE", "Celular"
        JEWELRY = "JEWELRY", "Joya"
        APPLIANCE = "APPLIANCE", "Electrodoméstico"
        CONSOLE = "CONSOLE", "Consola"
        INSTRUMENT = "INSTRUMENT", "Instrumento musical"
        OTHER = "OTHER", "Otro"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    contract = models.ForeignKey(
        "PawnContract",
        on_delete=models.CASCADE,
        related_name="items"
    )

    category = models.CharField(max_length=20, choices=Category.choices)

    # Descripción general
    description = models.TextField(blank=True)

    # ⚙️ Características técnicas (JSON flexible)
    attributes = models.JSONField(default=dict, blank=True)

    # 📦 Estado físico
    class Condition(models.TextChoices):
        EXCELLENT = "EXCELLENT", "Excelente"
        GOOD      = "GOOD",      "Bueno"
        WORN      = "WORN",      "Desgastado"
        DAMAGED   = "DAMAGED",   "Dañado"

    has_box      = models.BooleanField(default=False)
    has_charger  = models.BooleanField(default=False)
    condition    = models.CharField(max_length=20, choices=Condition.choices, default=Condition.GOOD,
                                    help_text="Estado del artículo: ajusta la sugerencia MVI")
    observations = models.TextField(blank=True)

    # Monto prestado por este artículo (parte proporcional del principal_amount)
    # Útil cuando hay múltiples artículos y se quiere calcular precio de venta por ítem.
    loan_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text="Capital prestado atribuido a este artículo específico",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category} - {self.contract.contract_number}"


class PawnAmortization(models.Model):
    """
    Adenda de amortización: el cliente paga interés + abona capital.
    Solo se crea cuando el contrato está en estado ACTIVO (today < due_date).
    """
    public_id      = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    contract       = models.ForeignKey(PawnContract, on_delete=models.PROTECT, related_name="amortizations")
    cash_session   = models.ForeignKey(CashSession,   on_delete=models.PROTECT, related_name="amortizations")
    performed_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="amortizations")
    performed_at   = models.DateTimeField(auto_now_add=True)

    outstanding_before  = models.DecimalField(max_digits=12, decimal_places=2)  # capital antes
    capital_paid        = models.DecimalField(max_digits=12, decimal_places=2)  # abono a capital
    interest_paid       = models.DecimalField(max_digits=12, decimal_places=2)  # UC cobrada

    previous_due_date   = models.DateField()
    new_due_date        = models.DateField()

    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Amortización"
        verbose_name_plural = "Amortizaciones"

    def __str__(self):
        return f"Amort {self.contract.contract_number} -{self.capital_paid}"


class Transfer(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        COMPLETED = "COMPLETED", "Completado"
        REJECTED = "REJECTED", "Rechazado"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    from_cash_register = models.ForeignKey(
        CashRegister, on_delete=models.PROTECT, related_name="transfers_out"
    )
    to_cash_register = models.ForeignKey(
        CashRegister, on_delete=models.PROTECT, related_name="transfers_in"
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transfers_created")
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="transfers_accepted")

    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    note = models.CharField(max_length=255, blank=True, default="")

# MODELO INVERSIONISTA
class Investor(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    full_name = models.CharField(max_length=255)
    ci        = models.CharField(max_length=50, blank=True)

    # % acordado de las utilidades generadas por sus contratos
    profit_rate_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("50.00"),
        help_text="Porcentaje de la utilidad (interés) que corresponde al inversionista. Ej: 50.00 = 50%",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name

    
# MODELO CUENTA DEL INVERSIONISTA
class InvestorAccount(models.Model):
    investor = models.OneToOneField(Investor, on_delete=models.CASCADE, related_name="account")

    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

# MODELO MOVIMIENTOS DEL INVERSIONISTA (LEDGER)
class InvestorMovement(models.Model):
    class MovementType(models.TextChoices):
        DEPOSIT = "DEPOSIT", "Ingreso"
        ASSIGN = "ASSIGN", "Asignado a contrato"
        RETURN = "RETURN", "Retorno de capital"
        PROFIT = "PROFIT", "Ganancia"
        WITHDRAW = "WITHDRAW", "Retiro"

    investor = models.ForeignKey(Investor, on_delete=models.PROTECT, related_name="movements")

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)

    related_contract = models.ForeignKey(
        "PawnContract",
        null=True,
        blank=True,
        on_delete=models.PROTECT
    )

    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)


# ─────────────────────────────────────────────
# MÓDULO CLIENTE (KYC + Scoring + WhatsApp)
# ─────────────────────────────────────────────

class Customer(models.Model):
    """
    Cliente normalizado con KYC completo, scoring de fidelidad
    y línea de crédito dinámica.
    """
    class Category(models.TextChoices):
        BRONCE = "BRONCE", "Bronce"
        PLATA  = "PLATA",  "Plata"
        ORO    = "ORO",    "Oro"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # ── Identidad (KYC) ──────────────────────────────
    ci = models.CharField(
        max_length=30, unique=True, db_index=True,
        help_text="Cédula de identidad — llave única del cliente",
    )
    first_name          = models.CharField(max_length=80)
    last_name_paternal  = models.CharField(max_length=80)
    last_name_maternal  = models.CharField(max_length=80, blank=True, default="")
    birth_date          = models.DateField(help_text="Necesaria para validar mayoría de edad")

    # ── Fotografías (Pillow / ImageField) ────────────
    photo_face = models.ImageField(
        upload_to="customers/faces/%Y/%m/",
        null=True, blank=True,
        help_text="Foto del rostro del cliente",
    )
    photo_ci = models.ImageField(
        upload_to="customers/ci_docs/%Y/%m/",
        null=True, blank=True,
        help_text="Foto/escaneo del documento de identidad",
    )

    # ── Contacto y ubicación ─────────────────────────
    phone   = models.CharField(max_length=20, help_text="Formato internacional: +591XXXXXXXX")
    email   = models.EmailField(blank=True, default="")
    address = models.TextField(blank=True, default="")
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # ── Estado / lista negra ─────────────────────────
    is_blacklisted   = models.BooleanField(default=False)
    blacklist_reason = models.TextField(blank=True, default="")

    # ── Scoring BI ───────────────────────────────────
    category = models.CharField(
        max_length=10, choices=Category.choices, default=Category.BRONCE,
    )

    # Tasa personalizada (anula política de categoría si está definida)
    custom_rate_pct = models.DecimalField(
        max_digits=6, decimal_places=2,
        null=True, blank=True,
        help_text="Tasa mensual personalizada. Vacío = usar política de categoría.",
    )

    score = models.IntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Puntaje 0-100 calculado por el motor de scoring",
    )

    # ── Contadores desnormalizados (performance) ─────
    total_contracts        = models.PositiveIntegerField(default=0)
    late_payments_count    = models.PositiveIntegerField(default=0)
    on_time_payments_count = models.PositiveIntegerField(default=0)

    # ── Auditoría ────────────────────────────────────
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="customers_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def __str__(self):
        return f"{self.full_name} (CI: {self.ci})"

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name_paternal]
        if self.last_name_maternal:
            parts.append(self.last_name_maternal)
        return " ".join(parts)

    @property
    def risk_color(self) -> str:
        """Verde ≥ 70 | Amarillo 40-69 | Rojo < 40"""
        if self.score >= 70:
            return "GREEN"
        if self.score >= 40:
            return "YELLOW"
        return "RED"

    @property
    def age(self) -> int:
        from datetime import date
        today = date.today()
        b = self.birth_date
        return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


class CustomerReference(models.Model):
    """
    Persona de referencia del cliente (familiar o amigo de confianza).
    """
    customer     = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="references")
    full_name    = models.CharField(max_length=120)
    phone        = models.CharField(max_length=20)
    relationship = models.CharField(max_length=60, blank=True, default="",
                                    help_text="Familiar, Amigo, Colega, etc.")

    class Meta:
        verbose_name = "Referencia de Cliente"
        verbose_name_plural = "Referencias de Cliente"

    def __str__(self):
        return f"{self.full_name} → {self.customer.ci}"


class WhatsAppMessage(models.Model):
    """
    Cola de mensajes WhatsApp Business.
    Cada registro es un intento de envío (pendiente, enviado, leído, fallido).
    El procesamiento real se hace en un worker/management command.
    """
    class Status(models.TextChoices):
        PENDING   = "PENDING",   "Pendiente de envío"
        SENT      = "SENT",      "Enviado"
        DELIVERED = "DELIVERED", "Entregado"
        READ      = "READ",      "Leído"
        FAILED    = "FAILED",    "Fallido"

    class EventType(models.TextChoices):
        DUE_REMINDER    = "DUE_REMINDER",    "Recordatorio Vencimiento (3 días)"
        OVERDUE_NOTICE  = "OVERDUE_NOTICE",  "Aviso de Mora"
        PAYMENT_CONFIRM = "PAYMENT_CONFIRM", "Confirmación de Pago"
        WELCOME         = "WELCOME",         "Bienvenida"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="whatsapp_messages",
    )
    contract = models.ForeignKey(
        "PawnContract", on_delete=models.PROTECT,
        null=True, blank=True, related_name="whatsapp_messages",
    )

    event_type = models.CharField(max_length=30, choices=EventType.choices)
    status     = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # Snapshot del número al momento de encolar (para auditoría)
    phone_to     = models.CharField(max_length=20)
    message_body = models.TextField()

    scheduled_for = models.DateTimeField(help_text="Cuándo debe enviarse este mensaje")
    sent_at       = models.DateTimeField(null=True, blank=True)

    # Respuesta de la API de WhatsApp
    wa_message_id = models.CharField(max_length=100, blank=True, default="")
    error_log     = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mensaje WhatsApp"
        verbose_name_plural = "Cola de WhatsApp"
        indexes = [
            # Índice compuesto para el worker: mensajes pendientes ordenados por fecha
            models.Index(fields=["status", "scheduled_for"], name="wa_status_schedule_idx"),
        ]

    def __str__(self):
        return f"[{self.status}] {self.event_type} → {self.customer.ci}"


# ─────────────────────────────────────────────
# FLUJO DE CAJA AVANZADO
# ─────────────────────────────────────────────

class CashDenomination(models.Model):
    """
    Matriz de denominaciones (billetes y monedas) registrada en
    la apertura y en el cierre de cada sesión de caja.

    Permite al sistema comparar el conteo físico contra el saldo
    lógico calculado y detectar diferencias al céntimo.
    """
    class DenomType(models.TextChoices):
        OPENING = "OPENING", "Apertura"
        CLOSING = "CLOSING", "Cierre"

    cash_session = models.ForeignKey(
        CashSession, on_delete=models.PROTECT, related_name="denominations",
    )
    denom_type   = models.CharField(max_length=10, choices=DenomType.choices)

    # ── Billetes (Bs.) ────────────────────────────────────────────
    b_200 = models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.200")
    b_100 = models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.100")
    b_50  = models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.50")
    b_20  = models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.20")
    b_10  = models.PositiveIntegerField(default=0, verbose_name="Billetes Bs.10")

    # ── Monedas (Bs.) ─────────────────────────────────────────────
    c_5   = models.PositiveIntegerField(default=0, verbose_name="Monedas Bs.5")
    c_2   = models.PositiveIntegerField(default=0, verbose_name="Monedas Bs.2")
    c_1   = models.PositiveIntegerField(default=0, verbose_name="Monedas Bs.1")

    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="denominations_counted",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Denominación de Caja"
        verbose_name_plural = "Denominaciones de Caja"
        unique_together = [("cash_session", "denom_type")]  # un conteo por tipo por sesión

    @property
    def total(self) -> Decimal:
        return (
            Decimal(self.b_200) * 200 + Decimal(self.b_100) * 100
            + Decimal(self.b_50) * 50 + Decimal(self.b_20) * 20
            + Decimal(self.b_10) * 10 + Decimal(self.c_5) * 5
            + Decimal(self.c_2) * 2  + Decimal(self.c_1) * 1
        )

    def to_dict(self) -> dict:
        return {
            "b_200": self.b_200, "b_100": self.b_100,
            "b_50":  self.b_50,  "b_20":  self.b_20, "b_10": self.b_10,
            "c_5":   self.c_5,   "c_2":   self.c_2,  "c_1":  self.c_1,
            "total": str(self.total),
        }

    def __str__(self):
        return f"{self.denom_type} | {self.cash_session} | Bs.{self.total}"


class CashExpense(models.Model):
    """
    Detalle de un gasto operativo (movimiento tipo EXPENSE_OUT).
    Vinculado 1:1 con el CashMovement correspondiente.
    Requiere descripción y permite adjuntar recibo.
    """
    class Category(models.TextChoices):
        UTILITIES   = "UTILITIES",   "Servicios (luz, agua, internet)"
        CLEANING    = "CLEANING",    "Limpieza"
        SUPPLIES    = "SUPPLIES",    "Útiles de oficina"
        MAINTENANCE = "MAINTENANCE", "Mantenimiento"
        SALARY      = "SALARY",      "Salario / Honorario"
        OTHER       = "OTHER",       "Otro"

    public_id     = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    cash_movement = models.OneToOneField(
        CashMovement, on_delete=models.PROTECT, related_name="expense_detail",
    )
    category    = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    description = models.TextField(help_text="Descripción obligatoria del gasto")
    receipt     = models.ImageField(
        upload_to="expenses/receipts/%Y/%m/", null=True, blank=True,
        help_text="Foto o escaneo del comprobante",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Gasto Operativo"
        verbose_name_plural = "Gastos Operativos"

    def __str__(self):
        return f"[{self.category}] {self.description[:40]} – {self.cash_movement.amount} Bs."

class InterestCategoryConfig(models.Model):
    """
    Configuración de tasas de interés por categoría de cliente.
    El dueño puede ajustar las tasas base sin tocar el código.
    Si no existe un registro para una categoría se usan los defaults del código.
    """
    class Category(models.TextChoices):
        BRONCE = "BRONCE", "Bronce"
        PLATA  = "PLATA",  "Plata"
        ORO    = "ORO",    "Oro"

    category = models.CharField(
        max_length=10, choices=Category.choices, unique=True,
    )
    base_rate_pct = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Tasa mensual base (%) para esta categoría. Sin límite de monto.",
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="interest_configs_updated",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración de Tasa por Categoría"
        verbose_name_plural = "Configuraciones de Tasas"

    def __str__(self):
        return f"{self.category}: {self.base_rate_pct}%"


# ─────────────────────────────────────────────────────────────────────────────
# FASE DE SINCRONIZACIÓN — Ajuste de saldo retroactivo
# ─────────────────────────────────────────────────────────────────────────────

class LegacyBalanceAdjustment(models.Model):
    """
    Ajuste de saldo inicial para la Fase de Sincronización (digitalización de
    contratos históricos 2023-2025).

    El dueño ingresa el saldo físico del libro para un día/mes determinado.
    El reporte de Conciliación compara este valor contra el saldo calculado
    por el sistema a partir de los movimientos digitalizados.
    """
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="legacy_adjustments",
    )
    adjustment_date = models.DateField(
        help_text="Fecha del libro físico que se está ajustando (ej: último día del mes).",
    )
    book_balance = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Saldo físico según el libro a esta fecha (Bs.).",
    )
    note = models.TextField(blank=True, default="",
        help_text="Observaciones opcionales del dueño.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="legacy_adjustments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ajuste de Saldo Legado"
        verbose_name_plural = "Ajustes de Saldo Legado"
        ordering = ["branch", "adjustment_date"]
        unique_together = [("branch", "adjustment_date")]

    def __str__(self):
        return f"{self.branch.code} | {self.adjustment_date} | Bs.{self.book_balance}"


# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO RRHH — importado desde models_hr.py para que Django lo descubra
# ─────────────────────────────────────────────────────────────────────────────
from core.models_hr import (  # noqa: E402
    HRConfig,
    Employee,
    SalaryScale,
    AttendanceRecord,
    SalaryPeriod,
    VacationPeriod,
    EmployeeTermination,
    AguinaldoPeriod,
)


# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO INVENTARIO — importado desde models_inventory.py
# ─────────────────────────────────────────────────────────────────────────────
from core.models_inventory import (  # noqa: E402
    DirectPurchase,
    DirectPurchasePhoto,
)

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO MVI — importado desde models_mvi.py
# ─────────────────────────────────────────────────────────────────────────────
from core.models_mvi import (  # noqa: E402
    MVIConfig,
    AppraisalOverride,
)
