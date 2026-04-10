from django.utils import timezone
from django.db import transaction

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from core.models import Transfer, CashRegister, CashSession, CashMovement
from core.api.serializers.transfer import TransferCreateSerializer
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes


# ==============================
# LISTAR / CREAR TRANSFERENCIA
# ==============================
class TransferCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Lista transferencias. Filtros: ?status=PENDING|COMPLETED|REJECTED"""
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        qs = Transfer.objects.select_related(
            "from_cash_register__branch",
            "to_cash_register__branch",
            "created_by",
            "accepted_by",
        ).order_by("-created_at")

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())

        # Cajeros solo ven transferencias hacia sus cajas
        if not is_owner_admin(request.user):
            allowed_codes = get_user_branch_codes(request.user)
            qs = qs.filter(
                to_cash_register__branch__code__in=allowed_codes
            ) | qs.filter(
                from_cash_register__branch__code__in=allowed_codes
            )
            qs = qs.distinct()

        transfers = [
            {
                "transfer_id":            str(t.public_id),
                "from_cash_register_id":  str(t.from_cash_register.public_id),
                "from_branch":            t.from_cash_register.branch.code if t.from_cash_register.branch else None,
                "to_cash_register_id":    str(t.to_cash_register.public_id),
                "to_branch":              t.to_cash_register.branch.code if t.to_cash_register.branch else None,
                "amount":                 str(t.amount),
                "status":                 t.status,
                "note":                   t.note,
                "created_by":             t.created_by.username if t.created_by else None,
                "created_at":             t.created_at,
                "accepted_by":            t.accepted_by.username if t.accepted_by else None,
                "accepted_at":            t.accepted_at,
            }
            for t in qs[:200]
        ]

        return Response({"count": len(transfers), "results": transfers})

    def post(self, request):
        serializer = TransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        require_roles(request.user, {"OWNER_ADMIN"})

        from_cr = CashRegister.objects.get(
            public_id=serializer.validated_data["from_cash_register_id"]
        )
        to_cr = CashRegister.objects.get(
            public_id=serializer.validated_data["to_cash_register_id"]
        )

        transfer = Transfer.objects.create(
            from_cash_register=from_cr,
            to_cash_register=to_cr,
            amount=serializer.validated_data["amount"],
            created_by=request.user,
            note=serializer.validated_data.get("note", "")
        )

        return Response({
            "transfer_id": str(transfer.public_id),
            "status": transfer.status
        }, status=status.HTTP_201_CREATED)


# ==============================
# ACEPTAR TRANSFERENCIA (CAJERO)
# ==============================
class TransferAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, transfer_id):

        try:
            transfer = Transfer.objects.get(public_id=transfer_id)
        except Transfer.DoesNotExist:
            return Response({"detail": "Transferencia no encontrada"}, status=404)

        if transfer.status != Transfer.Status.PENDING:
            return Response({"detail": "Transferencia ya procesada"}, status=400)

        with transaction.atomic():

            from_session = (
                CashSession.objects
                .select_for_update()
                .filter(
                    cash_register=transfer.from_cash_register,
                    status=CashSession.Status.OPEN
                )
                .first()
            )

            to_session = (
                CashSession.objects
                .select_for_update()
                .filter(
                    cash_register=transfer.to_cash_register,
                    status=CashSession.Status.OPEN
                )
                .first()
            )

            if not from_session or not to_session:
                return Response({"detail": "Sesión no abierta"}, status=409)

            # SALIDA
            CashMovement.objects.create(
                cash_session=from_session,
                cash_register=transfer.from_cash_register,
                branch=transfer.from_cash_register.branch,
                movement_type=CashMovement.MovementType.TRANSFER_OUT,
                amount=transfer.amount,
                performed_by=request.user,
                note=f"Transferencia enviada {transfer.public_id}"
            )

            # ENTRADA
            CashMovement.objects.create(
                cash_session=to_session,
                cash_register=transfer.to_cash_register,
                branch=transfer.to_cash_register.branch,
                movement_type=CashMovement.MovementType.TRANSFER_IN,
                amount=transfer.amount,
                performed_by=request.user,
                note=f"Transferencia recibida {transfer.public_id}"
            )

            transfer.status = Transfer.Status.COMPLETED
            transfer.accepted_by = request.user
            transfer.accepted_at = timezone.now()
            transfer.save()

        return Response({
            "detail": "Transferencia aceptada.",
            "transfer": {
                "transfer_id":          str(transfer.public_id),
                "from_cash_register_id": str(transfer.from_cash_register.public_id),
                "to_cash_register_id":   str(transfer.to_cash_register.public_id),
                "amount":               str(transfer.amount),
                "status":               transfer.status,
                "accepted_at":          transfer.accepted_at,
                "note":                 transfer.note,
            },
        })