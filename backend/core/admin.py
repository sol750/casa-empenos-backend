from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Branch,
    CashRegister,
    CashSession,
    CashMovement,
    PawnContract,
    PawnPayment,
    PawnRenewal,
    BranchCounter,
    PawnItem,
    Investor,
    InvestorAccount,
    InvestorMovement,
    Customer,
    CustomerReference,
    DirectPurchase,
    DirectPurchasePhoto
)

from .models_security import Role, UserRole, UserBranchAccess


# =============================
# BRANCH
# =============================
@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "created_at")
    search_fields = ("code", "name")
    list_filter = ("is_active",)


# =============================
# CASH REGISTER
# =============================
@admin.register(CashRegister)
class CashRegisterAdmin(admin.ModelAdmin):
    list_display = ("name", "register_type", "branch", "public_id", "is_active", "created_at")
    search_fields = ("name",)
    list_filter = ("register_type", "is_active", "branch")


# =============================
# CASH SESSION
# =============================
@admin.register(CashSession)
class CashSessionAdmin(admin.ModelAdmin):
    list_display = (
        "cash_register",
        "branch",
        "public_id",
        "status",
        "opening_amount",
        "opened_by",
        "opened_at",
        "closed_at",
    )
    list_filter = ("status", "branch", "cash_register")
    search_fields = ("cash_register__name",)


# =============================
# CASH MOVEMENT (LEDGER 🔥)
# =============================
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


# =============================
# SECURITY
# =============================
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


# =============================
# PAWN ITEMS INLINE 🔥
# =============================
class PawnItemInline(admin.TabularInline):
    model = PawnItem
    extra = 0


# =============================
# PAWN CONTRACT 🔥
# =============================
@admin.register(PawnContract)
class PawnContractAdmin(admin.ModelAdmin):
    list_display = (
        "contract_number",
        "customer_full_name",
        "principal_amount",
        "status",
        "branch",
        "investor",  # 🔥 NUEVO
        "created_by",
        "start_date",
        "due_date",
    )
    list_filter = ("status", "branch")
    search_fields = ("contract_number", "customer_full_name", "customer_ci")
    ordering = ("-created_at",)

    # 🔥 AQUÍ ves los items dentro del contrato
    inlines = [PawnItemInline]


# =============================
# PAWN ITEM
# =============================
@admin.register(PawnItem)
class PawnItemAdmin(admin.ModelAdmin):
    list_display = (
        "contract",
        "category",
        "description",
        "has_box",
        "has_charger",
        "created_at",
    )
    list_filter = ("category", "has_box", "has_charger")
    search_fields = ("contract__contract_number", "description")


# =============================
# PAYMENTS
# =============================
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


# =============================
# RENEWALS
# =============================
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


# =============================
# BRANCH COUNTER
# =============================
@admin.register(BranchCounter)
class BranchCounterAdmin(admin.ModelAdmin):
    list_display = ("branch", "pawn_contract_seq")


# =============================
# INVESTORS 🔥🔥🔥
# =============================
@admin.register(Investor)
class InvestorAdmin(admin.ModelAdmin):
    list_display = ("full_name", "ci", "created_at")
    search_fields = ("full_name", "ci")


@admin.register(InvestorAccount)
class InvestorAccountAdmin(admin.ModelAdmin):
    list_display = ("investor", "balance")
    search_fields = ("investor__full_name",)


@admin.register(InvestorMovement)
class InvestorMovementAdmin(admin.ModelAdmin):
    list_display = (
        "investor",
        "amount",
        "movement_type",
        "related_contract",
        "note",
        "created_at",
    )
    list_filter = ("movement_type",)
    search_fields = ("investor__full_name", "note")
    ordering = ("-created_at",)

class CustomerReferenceInline(admin.TabularInline):
    """Permite editar referencias directamente dentro del perfil del cliente"""
    model = CustomerReference
    extra = 1

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    # Columnas principales en la lista
    list_display = (
        'ci', 
        'full_name_display', 
        'category_badge', 
        'score_display', 
        'is_blacklisted', 
        'created_at'
    )
    
    # Buscador potente para tus 900 contratos
    search_fields = ('ci', 'first_name', 'last_name_paternal', 'last_name_maternal')
    
    # Filtros laterales rápidos
    list_filter = ('category', 'is_blacklisted', 'created_at')
    
    # Organización del formulario de edición
    fieldsets = (
        ('Identidad (KYC)', {
            'fields': (('ci', 'birth_date'), ('first_name', 'last_name_paternal', 'last_name_maternal'))
        }),
        ('Multimedia', {
            'fields': ('photo_face', 'photo_ci'),
            'classes': ('collapse',) # Se puede ocultar/mostrar
        }),
        ('Ubicación y Contacto', {
            'fields': (('phone', 'email'), 'address', ('gps_lat', 'gps_lon'))
        }),
        ('Scoring y Riesgo', {
            'fields': ('category', 'score', 'custom_rate_pct', 'is_blacklisted', 'blacklist_reason')
        }),
        ('Estadísticas (Lectura)', {
            'fields': (('total_contracts', 'late_payments_count', 'on_time_payments_count'),),
            'classes': ('collapse',)
        }),
        ('Auditoría', {
            'fields': ('created_by',),
        }),
    )

    inlines = [CustomerReferenceInline]

    # --- Funciones estéticas para el Admin ---

    def full_name_display(self, obj):
        return obj.full_name
    full_name_display.short_description = "Nombre Completo"

    def score_display(self, obj):
        """Muestra el score con el color de riesgo"""
        color = {
            "GREEN": "#28a745",
            "YELLOW": "#ffc107",
            "RED": "#dc3545"
        }.get(obj.risk_color, "#000")
        
        return format_html(
            '<b style="color: {};">{} pts</b>',
            color, obj.score
        )
    score_display.short_description = "Scoring"

    def category_badge(self, obj):
        """Muestra la categoría con estilo"""
        colors = {"ORO": "#FFD700", "PLATA": "#C0C0C0", "BRONCE": "#CD7F32"}
        return format_html(
            '<span style="background: {}; color: black; padding: 3px 10px; border-radius: 10px; font-weight: bold;">{}</span>',
            colors.get(obj.category, "#eee"), obj.category
        )
    category_badge.short_description = "Categoría"

# =============================
# DIRECT PURCHASE
# =============================
@admin.register(DirectPurchase)
class DirectPurchaseAdmin(admin.ModelAdmin):
    # Esto hará que la tabla sea legible y útil
    list_display = (
        'get_short_id', 
        'description_short', 
        'category', 
        'status', 
        'purchase_price', 
        'pvp', 
        'purchase_date'
    )
    # Filtros laterales por estado, categoría y fecha real de compra
    list_filter = ('status', 'category', 'purchase_date', 'branch')
    
    # Buscador por descripción y el CI del vendedor dentro del JSON
    search_fields = ('description', 'attributes__seller_ci', 'attributes__seller_name')
    
    # Campos de solo lectura para seguridad
    readonly_fields = ('created_at', 'public_id', 'projected_profit', 'actual_profit')
    
    # Organizar el formulario por fases (como lo tienes en el modelo)
    fieldsets = (
        ("Información Básica", {
            'fields': ('public_id', 'branch', 'status', 'category', 'description', 'attributes')
        }),
        ("Fase A: Adquisición", {
            'fields': ('cash_session', 'purchase_price', 'market_value_estimate', 'purchase_date', 'created_by', 'created_at')
        }),
        ("Fase B: Valoración (Venta)", {
            'fields': ('pvp', 'projected_profit', 'priced_by', 'priced_at', 'qr_code_data')
        }),
        ("Fase C: Liquidación", {
            'fields': ('sale_cash_session', 'sale_price', 'actual_profit', 'sold_by', 'sold_at')
        }),
    )

    def get_short_id(self, obj):
        return str(obj.public_id)[:8]
    get_short_id.short_description = "ID Corto"

    def description_short(self, obj):
        return obj.description[:50] + "..." if len(obj.description) > 50 else obj.description
    description_short.short_description = "Descripción"

@admin.register(DirectPurchasePhoto)
class DirectPurchasePhotoAdmin(admin.ModelAdmin):
   # Solo mostramos la relación con la compra. 
    # Si el campo de la imagen se llama 'image' o 'file', podrías agregarlo, 
    # pero por ahora dejemos solo 'purchase' para asegurar que funcione.
    list_display = ('purchase',)