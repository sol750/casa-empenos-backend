from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from core.models import Investor, PawnContract
from core.api.serializers.investor import InvestorCreateSerializer
from core.api.security import require_roles


def _investor_quick_summary(investor):
    """Resumen rápido: contratos activos y capital en la calle."""
    active = investor.contracts.filter(status=PawnContract.Status.ACTIVE)
    capital_active = sum(c.principal_amount for c in active)
    return {
        "investor_id":      str(investor.public_id),
        "full_name":        investor.full_name,
        "ci":               investor.ci,
        "profit_rate_pct":  str(investor.profit_rate_pct),
        "active_contracts": active.count(),
        "capital_at_risk":  f"{capital_active:,.2f}",
        "created_at":       investor.created_at.date().isoformat(),
    }


class InvestorCreateView(APIView):
    """
    POST /api/investor  → crear inversionista
    GET  /api/investor  → listar todos con resumen
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})
        investors = Investor.objects.prefetch_related("contracts").order_by("full_name")
        return Response({
            "investors": [_investor_quick_summary(inv) for inv in investors],
            "total":     investors.count(),
        })

    def post(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        serializer = InvestorCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        investor = Investor.objects.create(
            full_name       = v["full_name"],
            ci              = v.get("ci", ""),
            profit_rate_pct = v.get("profit_rate_pct", 50),
        )

        return Response(
            {
                "investor_id":     str(investor.public_id),
                "full_name":       investor.full_name,
                "ci":              investor.ci,
                "profit_rate_pct": str(investor.profit_rate_pct),
            },
            status=status.HTTP_201_CREATED,
        )