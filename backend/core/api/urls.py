from django.urls import path
from core.api.views.cash_register_alerts import CashRegisterAlertsView
from core.api.views.transfer import TransferCreateView
from core.api.views.cash_register_balance import CashRegisterBalancesView
from core.api.views.cash_session_current import CurrentCashSessionView
from core.api.views.me import MeView


from core.api.views.cash_session import OpenCashSessionView
from core.api.views.cash_register import CashRegisterListView
from core.api.views.pawn_contract import PawnContractCreateView
from core.api.views.pawn_payment import PawnPaymentCreateView
from core.api.views.pawn_renewal import PawnRenewalCreateView
from core.api.views.pawn_contract_detail import PawnContractDetailView
from core.api.views.pawn_contract_list import PawnContractListView
from core.api.views.cash_session_close import CashSessionCloseView
from core.api.views.cash_session_reopen import CashSessionReopenView
from core.api.views.cash_session_report import CashSessionClosingReportPDFView
from core.api.views.reports_daily_summary import DailySummaryReportView
from core.api.views.reports_daily_summary_pdf import DailySummaryReportPDFView
from core.api.views.cash_session_movements import CashSessionMovementsView
from core.api.views.users_admin import UserListCreateView, UserDetailUpdateView
from core.api.views.meta import RolesMetaView, BranchesMetaView

from core.api.views.cash_summary import CashSessionSummaryView



urlpatterns = [
    path("cash-registers/balances", CashRegisterBalancesView.as_view()),
    path("cash-registers/alerts", CashRegisterAlertsView.as_view()),
    path("cash-sessions/current", CurrentCashSessionView.as_view()),
    path("auth/me", MeView.as_view(), name="auth_me"),

   
    path("cash-registers", CashRegisterListView.as_view()),
    path("cash-sessions/open", OpenCashSessionView.as_view()), 
    path("transfers", TransferCreateView.as_view()), 
    path("pawn-contracts", PawnContractCreateView.as_view()), 
    path("pawn-contracts/payments", PawnPaymentCreateView.as_view()), 
    path("pawn-contracts/renew", PawnRenewalCreateView.as_view()),
    path("pawn-contracts/<uuid:contract_id>", PawnContractDetailView.as_view()),
    path("pawn-contracts/list", PawnContractListView.as_view()),
    path("cash-sessions/close", CashSessionCloseView.as_view()),
    path("cash-sessions/reopen", CashSessionReopenView.as_view()),
    path("cash-sessions/<uuid:cash_session_id>/closing-report.pdf", CashSessionClosingReportPDFView.as_view()),
    path("reports/daily-summary", DailySummaryReportView.as_view()),
    path("reports/daily-summary.pdf", DailySummaryReportPDFView.as_view()),
    path("cash-sessions/<uuid:cash_session_id>/movements", CashSessionMovementsView.as_view()),
    path("users", UserListCreateView.as_view()),
    path("users/<int:user_id>", UserDetailUpdateView.as_view()),
    path("meta/roles", RolesMetaView.as_view()),
    path("meta/branches", BranchesMetaView.as_view()),

    path("cash-sessions/<uuid:session_id>/summary", CashSessionSummaryView.as_view()),

]