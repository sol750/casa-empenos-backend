from django.contrib import admin

from .models import (
    Branch,
    CashRegister,
    CashSession,
    CashMovement, 
    PawnContract,
    PawnPayment,
    PawnRenewal,
    BranchCounter,
)

from .models_security import Role, UserRole, UserBranchAccess


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "created_at")
    search_fields = ("code", "name")
    list_filter = ("is_active",)


@admin.register(CashRegister)
class CashRegisterAdmin(admin.ModelAdmin):
    list_display = ("name", "register_type", "branch", "public_id", "is_active", "created_at")
    search_fields = ("name",)
    list_filter = ("register_type", "is_active", "branch")


@admin.register(CashSession)
class CashSessionAdmin(admin.ModelAdmin):
    list_display = ("cash_register", "branch", "public_id", "status", "opening_amount", "opened_by", "opened_at", "closed_at")
    list_filter = ("status", "branch", "cash_register")
    search_fields = ("cash_register__name",)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email", "role__code")


@admin.register(UserBranchAccess)
class UserBranchAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "branch")
    list_filter = ("branch",)
    search_fields = ("user__username", "user__email", "branch__code")


@admin.register(PawnContract)
class PawnContractAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "contract_number",
        "status",
        "branch",
        "customer_full_name",
        "principal_amount",
        "start_date",
        "due_date",
        "created_at",
    )
    list_filter = ("status", "branch")
    search_fields = ("contract_number", "customer_full_name", "customer_ci")
    ordering = ("-created_at",)


@admin.register(PawnPayment)
class PawnPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "contract",
        "paid_at",
        "amount",
        "interest_paid",
        "principal_paid",
        "paid_by",
    )
    list_filter = ("cash_session__branch",)
    search_fields = ("contract__contract_number",)
    ordering = ("-paid_at",)


@admin.register(PawnRenewal)
class PawnRenewalAdmin(admin.ModelAdmin):
    list_display = (
        "contract",
        "renewed_at",
        "previous_due_date",
        "new_due_date",
        "amount_charged",
        "interest_charged",
        "fee_charged",
        "renewed_by",
    )
    list_filter = ("cash_session__branch",)
    search_fields = ("contract__contract_number",)
    ordering = ("-renewed_at",)


@admin.register(BranchCounter)
class BranchCounterAdmin(admin.ModelAdmin):
    list_display = ("branch", "pawn_contract_seq")


@admin.register(CashMovement)
class CashMovementAdmin(admin.ModelAdmin):
    list_display = (
        "performed_at",
        "movement_type",
        "amount",
        "cash_register",
        "cash_session",
        "performed_by",
        "note",
    )
    list_filter = ("movement_type", "cash_register", "branch")
    search_fields = ("note", "cash_register__name", "performed_by__username")
    ordering = ("-performed_at",)


