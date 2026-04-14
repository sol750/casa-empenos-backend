"""
Configuración de Tasas de Interés — OWNER_ADMIN / CAJERO
=========================================================
  GET  /api/interest-rates/categories      — lista tasas por categoría
  PUT  /api/interest-rates/categories      — actualiza una o varias tasas
  GET  /api/customers/{ci}/rate            — tasa actual del cliente
  PATCH /api/customers/{ci}/rate           — establece/elimina tasa personalizada

Sin límites de monto: el dueño decide el capital manualmente.
"""
from decimal import Decimal, InvalidOperation

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.security import require_roles
from core.models import Customer, InterestCategoryConfig
from core.services.credit_line_calc import CATEGORY_CONFIG, MIN_ALLOWED_RATE


def _category_defaults():
    """Retorna la tasa actual (BD o default) para las 3 categorías."""
    result = {}
    for cat in ["BRONCE", "PLATA", "ORO"]:
        db_cfg = InterestCategoryConfig.objects.filter(category=cat).first()
        if db_cfg:
            result[cat] = {
                "base_rate_pct": str(db_cfg.base_rate_pct),
                "source":        "DB",
            }
        else:
            result[cat] = {
                "base_rate_pct": str(CATEGORY_CONFIG[cat]["base_rate"]),
                "source":        "DEFAULT",
            }
    return result


# ─────────────────────────────────────────────────────────────────────────────
class InterestCategoryConfigView(APIView):
    """
    GET  /api/interest-rates/categories
    PUT  /api/interest-rates/categories

    Body PUT:
    {
      "BRONCE": { "base_rate_pct": 10.00 },
      "PLATA":  { "base_rate_pct":  8.00 },
      "ORO":    { "base_rate_pct":  7.00 }
    }
    Solo se actualiza lo que se envía.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"OWNER_ADMIN", "CAJERO", "SUPERVISOR"})
        return Response({
            "min_allowed_rate": str(MIN_ALLOWED_RATE),
            "note":             "Sin límite de monto. El dueño decide el capital manualmente.",
            "categories":       _category_defaults(),
        })

    def put(self, request):
        require_roles(request.user, {"OWNER_ADMIN"})

        valid_cats = {"BRONCE", "PLATA", "ORO"}
        errors  = {}
        updated = []

        for cat, values in request.data.items():
            if cat not in valid_cats:
                errors[cat] = "Categoría inválida (BRONCE, PLATA, ORO)"
                continue

            cfg, _ = InterestCategoryConfig.objects.get_or_create(
                category=cat,
                defaults={
                    "base_rate_pct": CATEGORY_CONFIG[cat]["base_rate"],
                    "updated_by":    request.user,
                },
            )

            if "base_rate_pct" in values:
                try:
                    rate = Decimal(str(values["base_rate_pct"]))
                    if rate < MIN_ALLOWED_RATE:
                        errors[cat] = f"La tasa mínima permitida es {MIN_ALLOWED_RATE}%"
                        continue
                    cfg.base_rate_pct = rate
                except (InvalidOperation, TypeError):
                    errors[cat] = "'base_rate_pct' debe ser un número decimal"
                    continue

            cfg.updated_by = request.user
            cfg.save()
            updated.append(cat)

        if errors:
            return Response({"detail": "Errores en la actualización.", "errors": errors}, status=400)

        return Response({
            "updated":    updated,
            "categories": _category_defaults(),
        })


# ─────────────────────────────────────────────────────────────────────────────
class CustomerRateView(APIView):
    """
    GET  /api/customers/{ci}/rate
    PATCH /api/customers/{ci}/rate
         body: { "custom_rate_pct": 7.5 }
         body: { "custom_rate_pct": null } → eliminar personalización
    """
    permission_classes = [IsAuthenticated]

    def _get_customer(self, ci):
        try:
            return Customer.objects.get(ci=ci.upper())
        except Customer.DoesNotExist:
            return None

    def get(self, request, ci):
        require_roles(request.user, {"OWNER_ADMIN", "CAJERO", "SUPERVISOR"})
        customer = self._get_customer(ci)
        if not customer:
            return Response({"detail": "Cliente no encontrado."}, status=404)

        from core.services.credit_line_calc import _get_category_config
        cat_cfg = _get_category_config(customer.category)

        return Response({
            "ci":                 customer.ci,
            "full_name":          customer.full_name,
            "category":           customer.category,
            "category_base_rate": str(cat_cfg["base_rate"]),
            "custom_rate_pct":    str(customer.custom_rate_pct) if customer.custom_rate_pct else None,
            "effective_rate":     str(
                customer.custom_rate_pct if customer.custom_rate_pct
                else cat_cfg["base_rate"]
            ),
            "rate_source": "CUSTOM" if customer.custom_rate_pct else "CATEGORY",
        })

    def patch(self, request, ci):
        require_roles(request.user, {"OWNER_ADMIN", "CAJERO"})
        customer = self._get_customer(ci)
        if not customer:
            return Response({"detail": "Cliente no encontrado."}, status=404)

        raw = request.data.get("custom_rate_pct")

        if raw is None or str(raw).strip() == "" or raw == "null":
            customer.custom_rate_pct = None
            customer.save(update_fields=["custom_rate_pct"])
            from core.services.credit_line_calc import _get_category_config
            cat_cfg = _get_category_config(customer.category)
            return Response({
                "detail":          "Tasa personalizada eliminada. Se usará política de categoría.",
                "ci":              customer.ci,
                "custom_rate_pct": None,
                "effective_rate":  str(cat_cfg["base_rate"]),
                "rate_source":     "CATEGORY",
            })

        try:
            rate = Decimal(str(raw))
        except (InvalidOperation, TypeError):
            return Response({"detail": "'custom_rate_pct' debe ser un número decimal."}, status=400)

        if rate < MIN_ALLOWED_RATE:
            return Response(
                {"detail": f"La tasa mínima permitida es {MIN_ALLOWED_RATE}%."},
                status=400,
            )

        customer.custom_rate_pct = rate
        customer.save(update_fields=["custom_rate_pct"])

        return Response({
            "detail":          f"Tasa personalizada actualizada a {rate}% mensual.",
            "ci":              customer.ci,
            "full_name":       customer.full_name,
            "custom_rate_pct": str(rate),
            "rate_source":     "CUSTOM",
        })
