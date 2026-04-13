from django.urls import path

# ── Caja ──────────────────────────────────────────────────────────────────────
from core.api.views.cash_session import OpenCashSessionView
from core.api.views.cash_session_close import CashSessionCloseView
from core.api.views.cash_session_reopen import CashSessionReopenView
from core.api.views.cash_session_current import CurrentCashSessionView
from core.api.views.cash_session_movements import CashSessionMovementsView
from core.api.views.cash_session_report import CashSessionClosingReportPDFView
from core.api.views.cash_summary import CashSessionSummaryView
from core.api.views.cash import CashSessionBalanceView
from core.api.views.cash_register import CashRegisterListView
from core.api.views.cash_capital import (
    CashCapitalView,
    CashCapitalWithdrawView,
    CashCapitalHistoryView,
)
from core.api.views.cash_register_balance import CashRegisterBalancesView
from core.api.views.cash_register_alerts import CashRegisterAlertsView
from core.api.views.cash_denomination import CashDenominationView
from core.api.views.cash_expense import CashExpenseView, CashPurchaseView
from core.api.views.dashboard import CashDashboardView
from core.api.views.transfer import TransferCreateView, TransferAcceptView

# ── Contratos / Pagos / Renovaciones ─────────────────────────────────────────
from core.api.views.pawn_contract import PawnContractCreateView
from core.api.views.pawn_contract_detail import PawnContractDetailView
from core.api.views.pawn_contract_list import PawnContractListView
from core.api.views.pawn_payment import PawnPaymentCreateView
from core.api.views.pawn_renewal import PawnRenewalCreateView

# ── Reportes ──────────────────────────────────────────────────────────────────
from core.api.views.reports_daily_summary import DailySummaryReportView
from core.api.views.reports_daily_summary_pdf import DailySummaryReportPDFView
from core.api.views.reports_risk_concentration import RiskConcentrationReportView
from core.api.views.reports_default_summary import DefaultSummaryReportView

# ── Mora ──────────────────────────────────────────────────────────────────────
from core.api.views.pawn_contract_defaulted import PawnContractDefaultedView
from core.api.views.process_defaults_api import ProcessDefaultsView
from core.api.views.pawn_contract_cancel import PawnContractCancelView

# ── Amortización ──────────────────────────────────────────────────────────────
from core.api.views.pawn_amortization import (
    PawnContractStateView,
    PawnAmortizationPreviewView,
    PawnAmortizationCreateView,
)

# ── Inventario (Compra Directa + Vitrina) ─────────────────────────────────────
from core.api.views.inventory import (
    InventoryListView,
    InventoryDetailView,
    DirectPurchaseCreateView,
    InventoryPhotoUploadView,
    InventoryPriceView,
    InventoryQRView,
    InventorySellView,
    InventoryCancelView,
)

# ── Clientes / KYC / WhatsApp ─────────────────────────────────────────────────
from core.api.views.customer import (
    CustomerListCreateView,
    CustomerDetailView,
    CustomerPhotoUploadView,
)
from core.api.views.customer_dashboard import CustomerDashboardView
from core.api.views.customer_whatsapp import (
    QueueDueRemindersView,
    QueueOverdueNoticesView,
    WhatsAppPendingListView,
    WhatsAppMarkSentView,
    CustomerWhatsAppHistoryView,
)

# ── Auth / Usuarios / Meta ────────────────────────────────────────────────────
from core.api.views.me import MeView
from core.api.views.users_admin import UserListCreateView, UserDetailUpdateView
from core.api.views.meta import RolesMetaView, BranchesMetaView
from core.api.views.investor import InvestorCreateView
from core.api.views.investor_account import InvestorAccountView

# ── RRHH ──────────────────────────────────────────────────────────────────────
from core.api.views.hr_employee import (
    EmployeeListCreateView, EmployeeDetailView, EmployeeDocumentUploadView,
)
from core.api.views.hr_attendance import (
    ClockInView, ClockOutView, AttendanceListView, EmployeeAttendanceView,
)
from core.api.views.hr_payroll import (
    HRConfigView, PayrollGenerateView, PayrollListView,
    PayrollMonthView, PayrollDetailView,
)
from core.api.views.hr_vacation import EmployeeVacationView, VacationDetailView
from core.api.views.hr_aguinaldo import (
    AguinaldoGenerateView, AguinaldoYearView, AguinaldoPreviewView,
    AguinaldoDetailView, EmployeeAguinaldoHistoryView,
)
from core.api.views.reports_hr_aguinaldo import AguinaldoReportView
from core.api.views.reports_hr_payroll import PayrollReportView
from core.api.views.reports_hr_attendance import AttendanceReportView
from core.api.views.reports_hr_employees import EmployeeDirectoryReportView
from core.api.views.hr_termination import (
    EmployeeTerminationView, EmployeeAuditLogView,
)

# ── MVI (Motor de Valoración Inteligente) ─────────────────────────────────────
from core.api.views.mvi import (
    MVISuggestView,
    MVIConfigView,
    MVIOverrideCreateView,
    MVIOverrideListView,
    MVIOverrideAuthorizeView,
)
from core.api.views.whatsapp_mvi_notify import (
    MVIOverridePendingAlertView,
    MVIOverrideWhatsAppAlertView,
)

# ── Panel financiero del dueño ────────────────────────────────────────────────
from core.api.views.owner_treasury import OwnerTreasuryView
from core.api.views.owner_profitability import OwnerProfitabilityView
from core.api.views.owner_investors import (
    OwnerInvestorListView,
    OwnerInvestorStatementView,
    OwnerInvestorDepositView,
    OwnerInvestorProfitView,
    OwnerInvestorWithdrawView,
)
from core.api.views.reports_mvi import MVIOverrideReportView, MVIStatsReportView
from core.api.views.dashboard_owner import OwnerDashboardView
from core.api.views.reports_vitrina import VitrinaReportView

# ── Tasas de interés configurables ───────────────────────────────────────────
from core.api.views.interest_rate_config import (
    InterestCategoryConfigView,
    CustomerRateView,
)

# ── Gestión de sucursales y cajas (OWNER_ADMIN) ───────────────────────────────
from core.api.views.branch_management import (
    BranchListCreateView,
    BranchDetailView,
    BranchCashRegisterCreateView,
    CashRegisterSettingsView,
)


urlpatterns = [

    # ── Auth ──────────────────────────────────────────────────────────────────
    path("auth/me", MeView.as_view(), name="auth_me"),

    # ── Cajas ─────────────────────────────────────────────────────────────────
    path("cash-registers",                             CashRegisterListView.as_view()),
    path("cash-registers/<uuid:register_id>/capital",              CashCapitalView.as_view()),
    path("cash-registers/<uuid:register_id>/capital/withdraw",     CashCapitalWithdrawView.as_view()),
    path("cash-registers/<uuid:register_id>/capital/history",      CashCapitalHistoryView.as_view()),
    path("cash-registers/balances",                    CashRegisterBalancesView.as_view()),
    path("cash-registers/balance",                     CashRegisterBalancesView.as_view()),  # alias singular
    path("cash-registers/alerts",                      CashRegisterAlertsView.as_view()),

    path("cash-sessions/open",                         OpenCashSessionView.as_view()),
    path("cash-sessions/close",                        CashSessionCloseView.as_view()),
    path("cash-sessions/reopen",                       CashSessionReopenView.as_view()),
    path("cash-sessions/current",                      CurrentCashSessionView.as_view()),
    path("cash-sessions/<uuid:session_id>/summary",    CashSessionSummaryView.as_view()),
    path("cash-sessions/<uuid:session_id>/balance",    CashSessionBalanceView.as_view()),
    path("cash-sessions/<uuid:cash_session_id>/movements",          CashSessionMovementsView.as_view()),
    path("cash-sessions/<uuid:cash_session_id>/closing-report.pdf", CashSessionClosingReportPDFView.as_view()),
    path("cash-sessions/<uuid:session_id>/denomination",             CashDenominationView.as_view()),
    path("cash-sessions/<uuid:session_id>/expenses",                 CashExpenseView.as_view()),
    path("cash-sessions/<uuid:session_id>/purchases",                CashPurchaseView.as_view()),

    path("transfers",                                  TransferCreateView.as_view()),
    path("transfers/<uuid:transfer_id>/accept",        TransferAcceptView.as_view()),

    # ── Dashboard ─────────────────────────────────────────────────────────────
    path("dashboard/cash",                             CashDashboardView.as_view()),

    # ── Contratos ─────────────────────────────────────────────────────────────
    path("pawn-contracts",                             PawnContractCreateView.as_view()),
    path("pawn-contracts/list",                        PawnContractListView.as_view()),
    path("pawn-contracts/payments",                    PawnPaymentCreateView.as_view()),
    path("pawn-contracts/renew",                       PawnRenewalCreateView.as_view()),
    path("pawn-contracts/cancel",                        PawnContractCancelView.as_view()),
    path("pawn-contracts/defaulted",                   PawnContractDefaultedView.as_view()),
    path("pawn-contracts/process-defaults",            ProcessDefaultsView.as_view()),
    path("pawn-contracts/<uuid:contract_id>",                           PawnContractDetailView.as_view()),
    path("pawn-contracts/<uuid:contract_id>/state",                    PawnContractStateView.as_view()),
    path("pawn-contracts/<uuid:contract_id>/amortize/preview",         PawnAmortizationPreviewView.as_view()),
    path("pawn-contracts/<uuid:contract_id>/amortize",                 PawnAmortizationCreateView.as_view()),

    # ── Inventario ────────────────────────────────────────────────────────────
    path("inventory",                                                   InventoryListView.as_view()),
    path("inventory/direct-purchase",                                   DirectPurchaseCreateView.as_view()),
    path("inventory/<uuid:purchase_id>",                               InventoryDetailView.as_view()),
    path("inventory/<uuid:purchase_id>/photos",                        InventoryPhotoUploadView.as_view()),
    path("inventory/<uuid:purchase_id>/price",                         InventoryPriceView.as_view()),
    path("inventory/<uuid:purchase_id>/qr",                            InventoryQRView.as_view()),
    path("inventory/<uuid:purchase_id>/sell",                          InventorySellView.as_view()),
    path("inventory/<uuid:purchase_id>/cancel",                        InventoryCancelView.as_view()),

    # ── Reportes ──────────────────────────────────────────────────────────────
    path("reports/daily-summary",                      DailySummaryReportView.as_view()),
    path("reports/daily-summary.pdf",                  DailySummaryReportPDFView.as_view()),
    path("reports/risk-concentration",                 RiskConcentrationReportView.as_view()),
    path("reports/default-summary",                    DefaultSummaryReportView.as_view()),

    # ── Clientes (KYC + Scoring) ──────────────────────────────────────────────
    path("customers",                                  CustomerListCreateView.as_view()),
    path("customers/<str:ci>",                         CustomerDetailView.as_view()),
    path("customers/<str:ci>/dashboard",               CustomerDashboardView.as_view()),
    path("customers/<str:ci>/photos",                  CustomerPhotoUploadView.as_view()),
    path("customers/<str:ci>/whatsapp",                CustomerWhatsAppHistoryView.as_view()),

    # ── WhatsApp / Cola de mensajes ───────────────────────────────────────────
    path("whatsapp/queue-reminders",                   QueueDueRemindersView.as_view()),
    path("whatsapp/queue-overdue",                     QueueOverdueNoticesView.as_view()),
    path("whatsapp/pending",                           WhatsAppPendingListView.as_view()),
    path("whatsapp/<uuid:public_id>/mark-sent",        WhatsAppMarkSentView.as_view()),

    # ── Usuarios / Meta ───────────────────────────────────────────────────────
    path("users",                                      UserListCreateView.as_view()),
    path("users/<int:user_id>",                        UserDetailUpdateView.as_view()),
    path("meta/roles",                                 RolesMetaView.as_view()),
    path("meta/branches",                              BranchesMetaView.as_view()),

    # ── Inversores ────────────────────────────────────────────────────────────
    path("investor",                                   InvestorCreateView.as_view()),
    path("investors",                                  InvestorCreateView.as_view()),
    path("investors/<uuid:investor_id>/account",       InvestorAccountView.as_view()),

    # ── RRHH — Configuración ──────────────────────────────────────────────────
    path("hr/config",                                  HRConfigView.as_view()),

    # ── RRHH — Empleados ──────────────────────────────────────────────────────
    path("hr/employees",                               EmployeeListCreateView.as_view()),
    path("hr/employees/<uuid:employee_id>",            EmployeeDetailView.as_view()),
    path("hr/employees/<uuid:employee_id>/documents",  EmployeeDocumentUploadView.as_view()),
    path("hr/employees/<uuid:employee_id>/attendance", EmployeeAttendanceView.as_view()),
    path("hr/employees/<uuid:employee_id>/vacations",  EmployeeVacationView.as_view()),
    path("hr/employees/<uuid:employee_id>/terminate",  EmployeeTerminationView.as_view()),
    path("hr/employees/<uuid:employee_id>/audit-log",  EmployeeAuditLogView.as_view()),
    path("hr/employees/<uuid:employee_id>/aguinaldos", EmployeeAguinaldoHistoryView.as_view()),

    # ── RRHH — Asistencia ─────────────────────────────────────────────────────
    path("hr/attendance/clock-in",                     ClockInView.as_view()),
    path("hr/attendance/clock-out",                    ClockOutView.as_view()),
    path("hr/attendance",                              AttendanceListView.as_view()),

    # ── RRHH — Planilla ───────────────────────────────────────────────────────
    path("hr/payroll/generate",                        PayrollGenerateView.as_view()),
    path("hr/payroll",                                 PayrollListView.as_view()),
    path("hr/payroll/<int:year>/<int:month>",          PayrollMonthView.as_view()),
    path("hr/payroll/<int:period_id>",                 PayrollDetailView.as_view()),

    # ── RRHH — Vacaciones ─────────────────────────────────────────────────────
    path("hr/vacations/<int:vacation_id>",             VacationDetailView.as_view()),

    # ── RRHH — Aguinaldo ─────────────────────────────────────────────────────
    path("hr/aguinaldo/generate",                      AguinaldoGenerateView.as_view()),
    path("hr/aguinaldo/<int:year>/preview",            AguinaldoPreviewView.as_view()),
    path("hr/aguinaldo/<int:year>",                    AguinaldoYearView.as_view()),
    path("hr/aguinaldo/detail/<int:aguinaldo_id>",     AguinaldoDetailView.as_view()),

    # ── MVI ───────────────────────────────────────────────────────────────────
    path("mvi/suggest",                                    MVISuggestView.as_view()),
    path("mvi/config",                                     MVIConfigView.as_view()),
    path("mvi/overrides",                                  MVIOverrideListView.as_view()),
    path("mvi/overrides/create",                           MVIOverrideCreateView.as_view()),
    path("mvi/overrides/pending-alert",                    MVIOverridePendingAlertView.as_view()),
    path("mvi/overrides/whatsapp-alert",                   MVIOverrideWhatsAppAlertView.as_view()),
    path("mvi/overrides/<uuid:override_id>/authorize",     MVIOverrideAuthorizeView.as_view(), kwargs={"action": "authorize"}),
    path("mvi/overrides/<uuid:override_id>/deny",          MVIOverrideAuthorizeView.as_view(), kwargs={"action": "deny"}),

    # ── Dashboard dueño ──────────────────────────────────────────────────────
    path("dashboard/owner",                            OwnerDashboardView.as_view()),

    # ── Panel financiero del dueño ────────────────────────────────────────────
    path("owner/treasury",                             OwnerTreasuryView.as_view()),
    path("owner/profitability",                        OwnerProfitabilityView.as_view()),
    path("owner/investors",                            OwnerInvestorListView.as_view()),
    path("owner/investors/<uuid:investor_id>/statement",  OwnerInvestorStatementView.as_view()),
    path("owner/investors/<uuid:investor_id>/deposit",    OwnerInvestorDepositView.as_view()),
    path("owner/investors/<uuid:investor_id>/profit",     OwnerInvestorProfitView.as_view()),
    path("owner/investors/<uuid:investor_id>/withdraw",   OwnerInvestorWithdrawView.as_view()),

    # ── Reportes MVI ─────────────────────────────────────────────────────────
    path("reports/mvi/overrides",                      MVIOverrideReportView.as_view()),
    path("reports/mvi/stats",                          MVIStatsReportView.as_view()),

    # ── Reporte vitrina (contratos en mora/venta) ─────────────────────────────
    path("reports/vitrina",                            VitrinaReportView.as_view()),

    # ── Reportes RRHH ────────────────────────────────────────────────────────
    path("reports/hr/aguinaldo/<int:year>",            AguinaldoReportView.as_view()),
    path("reports/hr/payroll/<int:year>/<int:month>",  PayrollReportView.as_view()),
    path("reports/hr/attendance/<int:year>/<int:month>", AttendanceReportView.as_view()),
    path("reports/hr/employees",                       EmployeeDirectoryReportView.as_view()),

    # ── Tasas de interés ──────────────────────────────────────────────────────
    path("interest-rates/categories",                  InterestCategoryConfigView.as_view()),
    path("customers/<str:ci>/rate",                    CustomerRateView.as_view()),

    # ── Gestión de sucursales y cajas ────────────────────────────────────────
    path("branches",                                   BranchListCreateView.as_view()),
    path("branches/<int:branch_id>",                   BranchDetailView.as_view()),
    path("branches/<int:branch_id>/cash-registers",    BranchCashRegisterCreateView.as_view()),
    path("cash-registers/<uuid:register_id>/settings", CashRegisterSettingsView.as_view()),
]