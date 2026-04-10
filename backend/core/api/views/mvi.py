"""
MVI (Motor de Valoración Inteligente) — API Views

Endpoints:
  GET  /api/mvi/suggest            — sugerencia en tiempo real para el cajero
  GET  /api/mvi/config             — ver configuración actual
  POST /api/mvi/config             — actualizar configuración (OWNER_ADMIN)
  GET  /api/mvi/overrides          — listar solicitudes pendientes (OWNER_ADMIN)
  POST /api/mvi/overrides/{id}/authorize — aprobar override
  POST /api/mvi/overrides/{id}/deny      — rechazar override
  POST /api/mvi/overrides          — crear solicitud de override (cajero, cuando hay HARD_BLOCK)
"""
from decimal import Decimal
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models_mvi import MVIConfig, AppraisalOverride
from core.api.security import require_roles
from core.services.mvi_engine import get_mvi_suggestion, validate_principal_against_mvi


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/mvi/suggest
# ─────────────────────────────────────────────────────────────────────────────
class MVISuggestView(APIView):
    """
    Sugerencia de monto de préstamo en tiempo real.

    Query params:
      category     — PHONE | LAPTOP | CONSOLE | APPLIANCE | JEWELRY | INSTRUMENT | OTHER
      description  — texto libre del artículo
      condition    — EXCELLENT | GOOD | WORN | DAMAGED  (default GOOD)
      karat        — kilataje (solo JEWELRY)
      weight_grams — peso en gramos (solo JEWELRY)
      metal        — GOLD | SILVER (solo JEWELRY, default GOLD)
      customer_ci  — CI del cliente (para bonus VIP si es ORO)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        category    = request.query_params.get("category", "").upper()
        description = request.query_params.get("description", "").strip()
        condition   = request.query_params.get("condition", "GOOD").upper()
        customer_ci = request.query_params.get("customer_ci", "").strip().upper()

        valid_categories = {"PHONE", "LAPTOP", "CONSOLE", "APPLIANCE", "JEWELRY", "INSTRUMENT", "OTHER"}
        if category not in valid_categories:
            return Response(
                {"detail": f"Categoría inválida. Opciones: {', '.join(sorted(valid_categories))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not description:
            return Response({"detail": "El campo 'description' es requerido."}, status=status.HTTP_400_BAD_REQUEST)

        # Atributos de joyería
        attributes = {}
        if category == "JEWELRY":
            if request.query_params.get("karat"):
                attributes["karat"] = request.query_params["karat"]
            if request.query_params.get("weight_grams"):
                attributes["weight_grams"] = request.query_params["weight_grams"]
            if request.query_params.get("metal"):
                attributes["metal"] = request.query_params["metal"]

        # Categoría VIP del cliente (si tiene CI)
        customer_category = None
        if customer_ci:
            from core.models import Customer
            cust = Customer.objects.filter(ci=customer_ci).first()
            if cust:
                customer_category = cust.category

        suggestion = get_mvi_suggestion(
            category=category,
            description=description,
            condition=condition,
            attributes=attributes,
            customer_category=customer_category,
        )

        return Response(suggestion)


# ─────────────────────────────────────────────────────────────────────────────
# GET/POST /api/mvi/config
# ─────────────────────────────────────────────────────────────────────────────
class MVIConfigView(APIView):
    """
    GET  — ver configuración actual (SUPERVISOR, OWNER_ADMIN)
    POST — actualizar (OWNER_ADMIN)
    """
    permission_classes = [IsAuthenticated]

    EDITABLE_FIELDS = [
        "gold_price_24k_gram_bs",
        "silver_price_gram_bs",
        "depreciation_phone_pct",
        "depreciation_laptop_pct",
        "depreciation_console_pct",
        "depreciation_appliance_pct",
        "depreciation_other_pct",
        "loan_to_value_pct",
        "vip_bonus_pct",
        "soft_warning_pct",
        "hard_block_pct",
    ]

    def get(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})
        cfg = MVIConfig.get()
        return Response(self._serialize(cfg))

    def post(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})
        cfg = MVIConfig.get()

        updated = []
        errors  = {}
        for field in self.EDITABLE_FIELDS:
            if field in request.data:
                try:
                    value = Decimal(str(request.data[field]))
                    if value < 0:
                        errors[field] = "El valor no puede ser negativo."
                        continue
                    setattr(cfg, field, value)
                    updated.append(field)
                except Exception:
                    errors[field] = "Valor decimal inválido."

        if errors:
            return Response({"detail": "Errores de validación.", "errors": errors},
                            status=status.HTTP_400_BAD_REQUEST)

        if updated:
            cfg.updated_by = request.user
            cfg.save()

        return Response({
            "updated_fields": updated,
            "config": self._serialize(cfg),
        })

    def _serialize(self, cfg):
        return {
            "gold_price_24k_gram_bs":    str(cfg.gold_price_24k_gram_bs),
            "silver_price_gram_bs":      str(cfg.silver_price_gram_bs),
            "depreciation_phone_pct":    str(cfg.depreciation_phone_pct),
            "depreciation_laptop_pct":   str(cfg.depreciation_laptop_pct),
            "depreciation_console_pct":  str(cfg.depreciation_console_pct),
            "depreciation_appliance_pct": str(cfg.depreciation_appliance_pct),
            "depreciation_other_pct":    str(cfg.depreciation_other_pct),
            "loan_to_value_pct":         str(cfg.loan_to_value_pct),
            "vip_bonus_pct":             str(cfg.vip_bonus_pct),
            "soft_warning_pct":          str(cfg.soft_warning_pct),
            "hard_block_pct":            str(cfg.hard_block_pct),
            "updated_at": str(cfg.updated_at) if cfg.updated_at else None,
            "updated_by": cfg.updated_by.get_full_name() if cfg.updated_by else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/mvi/overrides  (cajero crea la solicitud)
# ─────────────────────────────────────────────────────────────────────────────
class MVIOverrideCreateView(APIView):
    """
    El cajero crea una solicitud de autorización cuando el MVI bloquea el monto.
    El dueño la aprueba o rechaza desde su panel.

    Body:
      branch_id          — UUID de la sucursal
      category           — categoría del artículo
      description        — descripción del artículo
      condition          — condición
      customer_ci        — CI del cliente (opcional)
      system_recommendation   — del response MVI
      system_max_allowed      — del response MVI
      principal_requested     — monto que el cajero quiere prestar
      override_reason         — justificación
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        required = [
            "branch_id", "category", "description", "condition",
            "system_recommendation", "system_max_allowed",
            "principal_requested", "override_reason",
        ]
        missing = [f for f in required if not request.data.get(f)]
        if missing:
            return Response(
                {"detail": "Campos requeridos faltantes.", "missing": missing},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from core.models import Branch
        try:
            branch = Branch.objects.get(public_id=request.data["branch_id"])
        except Branch.DoesNotExist:
            return Response({"detail": "Sucursal no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        try:
            override = AppraisalOverride.objects.create(
                branch=branch,
                category=request.data["category"].upper(),
                description=request.data["description"],
                condition=request.data.get("condition", "GOOD").upper(),
                customer_ci=request.data.get("customer_ci", "").strip().upper(),
                system_recommendation=Decimal(str(request.data["system_recommendation"])),
                system_max_allowed=Decimal(str(request.data["system_max_allowed"])),
                principal_requested=Decimal(str(request.data["principal_requested"])),
                override_reason=request.data["override_reason"],
                requested_by=request.user,
            )
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "override_id":         str(override.public_id),
                "status":              override.status,
                "system_recommendation": str(override.system_recommendation),
                "principal_requested": str(override.principal_requested),
                "message": "Solicitud enviada. El dueño debe autorizarla antes de crear el contrato.",
            },
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/mvi/overrides  (dueño lista pendientes)
# ─────────────────────────────────────────────────────────────────────────────
class MVIOverrideListView(APIView):
    """
    Lista solicitudes de autorización.
    ?status=PENDING|APPROVED|DENIED  (default: PENDING)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        filter_status = request.query_params.get("status", "PENDING").upper()
        qs = AppraisalOverride.objects.select_related(
            "branch", "requested_by", "authorized_by"
        ).filter(status=filter_status).order_by("-requested_at")

        results = []
        for ov in qs:
            results.append({
                "override_id":         str(ov.public_id),
                "status":              ov.status,
                "branch_code":         ov.branch.code,
                "category":            ov.category,
                "description":         ov.description,
                "condition":           ov.condition,
                "customer_ci":         ov.customer_ci,
                "system_recommendation": str(ov.system_recommendation),
                "system_max_allowed":  str(ov.system_max_allowed),
                "principal_requested": str(ov.principal_requested),
                "override_reason":     ov.override_reason,
                "requested_by":        ov.requested_by.get_full_name(),
                "requested_at":        str(ov.requested_at),
                "authorized_by":       ov.authorized_by.get_full_name() if ov.authorized_by else None,
                "authorized_at":       str(ov.authorized_at) if ov.authorized_at else None,
                "authorization_note":  ov.authorization_note,
            })

        return Response({"count": len(results), "results": results})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/mvi/overrides/{id}/authorize
# POST /api/mvi/overrides/{id}/deny
# ─────────────────────────────────────────────────────────────────────────────
class MVIOverrideAuthorizeView(APIView):
    """
    Aprueba o rechaza una solicitud de sobre-tasación.
    Solo OWNER_ADMIN.
    Body (deny): { "authorization_note": "..." }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, override_id, action):
        require_roles(request.user, {"OWNER_ADMIN"})

        try:
            override = AppraisalOverride.objects.get(public_id=override_id)
        except AppraisalOverride.DoesNotExist:
            return Response({"detail": "Solicitud no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        if override.status != AppraisalOverride.Status.PENDING:
            return Response(
                {"detail": f"La solicitud ya fue procesada ({override.status})."},
                status=status.HTTP_409_CONFLICT,
            )

        note = request.data.get("authorization_note", "").strip()

        if action == "authorize":
            override.status         = AppraisalOverride.Status.APPROVED
            override.authorized_by  = request.user
            override.authorized_at  = timezone.now()
            override.authorization_note = note
            override.save()
            return Response({
                "override_id": str(override.public_id),
                "status":      override.status,
                "message":     "Autorización aprobada. El cajero puede proceder a crear el contrato.",
                "principal_requested": str(override.principal_requested),
            })

        if action == "deny":
            if not note:
                return Response(
                    {"detail": "Se requiere 'authorization_note' para rechazar."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            override.status         = AppraisalOverride.Status.DENIED
            override.authorized_by  = request.user
            override.authorized_at  = timezone.now()
            override.authorization_note = note
            override.save()
            return Response({
                "override_id": str(override.public_id),
                "status":      override.status,
                "message":     "Solicitud rechazada.",
                "reason":      note,
            })

        return Response({"detail": "Acción inválida. Use 'authorize' o 'deny'."}, status=400)
