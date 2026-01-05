import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone


class Branch(models.Model):
    """
    Sucursal.
    """
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True)  # ej: PT1, PT2
    is_active = models.BooleanField(default=True)

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
    Caja física/lógica. Puede ser de sucursal o global.
    """
    class RegisterType(models.TextChoices):
        BRANCH = "BRANCH", "Sucursal"
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

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Caja"
        verbose_name_plural = "Cajas"
        constraints = [
            # Si es BRANCH, branch NO puede ser null
            models.CheckConstraint(
                check=Q(register_type="GLOBAL", branch__isnull=True) | Q(register_type="BRANCH", branch__isnull=False),
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
        if self.closing_expected_amount is not None:
            return self.closing_expected_amount

        total = self.opening_amount

        for m in self.movements.all():
            mt = (m.movement_type or "").upper().strip()
            if mt.endswith("_IN"):
                total += m.amount
            elif mt.endswith("_OUT"):
                total -= m.amount

        return total

    
class CashMovement(models.Model):
    """
    Movimiento de dinero asociado a una sesión de caja.
    Base para auditoría y cálculo de expected.
    """
    class MovementType(models.TextChoices):
        TRANSFER_IN = "TRANSFER_IN", "Transferencia Entrante"
        TRANSFER_OUT = "TRANSFER_OUT", "Transferencia Saliente"
        ADJUSTMENT_IN = "ADJUSTMENT_IN", "Ajuste Sobrante"
        ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Ajuste Faltante"
        LOAN_OUT = "LOAN_OUT", "Desembolso Préstamo"
        PAYMENT_IN = "PAYMENT_IN", "Pago/Abono"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="movements")
    cash_register = models.ForeignKey(CashRegister, on_delete=models.PROTECT, related_name="movements")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="cash_movements")

    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_movements")
    performed_at = models.DateTimeField(auto_now_add=True)

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
        ACTIVE = "ACTIVE", "Activo"
        CLOSED = "CLOSED", "Cerrado"
        DEFAULTED = "DEFAULTED", "En mora"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    contract_number = models.CharField(max_length=30, unique=True)  # Ej: PT1-000001

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pawn_contracts")
    created_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    # Cliente (MVP: texto; luego lo normalizamos en tabla Client)
    customer_full_name = models.CharField(max_length=120)
    customer_ci = models.CharField(max_length=30, blank=True, default="")

    # Préstamo
    principal_amount = models.DecimalField(max_digits=12, decimal_places=2)  # capital
    interest_rate_monthly = models.DecimalField(max_digits=6, decimal_places=2, default=8.00)  # 8% mensual
    start_date = models.DateField(default=timezone.now)
    due_date = models.DateField()  # fecha vencimiento

    # Promos / prorrateo: guardamos regla aplicada para auditoría
    interest_mode = models.CharField(
        max_length=20,
        default="MONTHLY_PRORATED",
        help_text="MONTHLY_PRORATED (por días) / FIXED / PROMO"
    )
    promo_note = models.CharField(max_length=255, blank=True, default="")

    # Caja / desembolso
    disbursed_cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="pawn_disbursements")

    def __str__(self):
        return self.contract_number
    
    interest_accrued_until = models.DateField(null=True, blank=True)


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

from .models_security import Role, UserRole, UserBranchAccess  # noqa: F401
