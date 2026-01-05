from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PawnContract
from core.models_security import UserRole


class PawnContractListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        roles = set(UserRole.objects.filter(user=request.user).values_list("role__code", flat=True))
        allowed_roles = {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}
        if not roles.intersection(allowed_roles):
            return Response({"detail": "No tiene permisos."}, status=403)

        qs = PawnContract.objects.select_related("branch").order_by("-created_at")

        # Restricción por sucursal si no es dueño
        if "OWNER_ADMIN" not in roles:
            branch_ids = request.user.branch_access.values_list("branch_id", flat=True)
            qs = qs.filter(branch_id__in=branch_ids)

        # filtros
        branch_code = request.query_params.get("branch")
        status_param = request.query_params.get("status")
        search = request.query_params.get("search")

        if branch_code:
            qs = qs.filter(branch__code=branch_code)
        if status_param:
            qs = qs.filter(status=status_param)
        if search:
            qs = qs.filter(customer_full_name__icontains=search)

        data = []
        for c in qs[:100]:
            data.append(
                {
                    "pawn_contract_id": str(c.public_id),
                    "contract_number": c.contract_number,
                    "status": c.status,
                    "branch_code": c.branch.code,
                    "customer_full_name": c.customer_full_name,
                    "principal_amount": str(c.principal_amount),
                    "due_date": str(c.due_date),
                    "created_at": c.created_at.isoformat(),
                }
            )

        return Response(data)
