from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.models import PawnContract
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes


class PawnContractListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        allowed_roles = {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"}

        # 1) Roles
        try:
            require_roles(request.user, allowed_roles)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

        qs = PawnContract.objects.select_related("branch", "customer").order_by("-created_at")

        # 2) Restricción por sucursal si no es dueño
        user_allowed_branch_codes = set()
        if not is_owner_admin(request.user):
            user_allowed_branch_codes = get_user_branch_codes(request.user)
            qs = qs.filter(branch__code__in=user_allowed_branch_codes)

        # 3) Filtros (validando branch si no es OWNER)
        branch_code = request.query_params.get("branch")
        status_param = request.query_params.get("status")
        search = request.query_params.get("search")

        if branch_code:
            if not is_owner_admin(request.user) and branch_code not in user_allowed_branch_codes:
                return Response({"detail": "No tiene acceso a esta sucursal."}, status=status.HTTP_403_FORBIDDEN)
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

        return Response(data, status=status.HTTP_200_OK)
