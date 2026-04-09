from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from core.models import Investor
from core.api.serializers.investor import InvestorCreateSerializer


class InvestorCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InvestorCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        investor = Investor.objects.create(
            full_name=serializer.validated_data["full_name"],
            ci=serializer.validated_data.get("ci", "")
        )

        return Response(
            {
                "investor_id": str(investor.public_id),
                "full_name": investor.full_name,
                "ci": investor.ci
            },
            status=status.HTTP_201_CREATED
        )