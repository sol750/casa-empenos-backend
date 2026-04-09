"""
Vistas CRUD del Módulo Cliente
POST   /api/customers              → Crear cliente
GET    /api/customers              → Listar / buscar clientes
GET    /api/customers/<ci>         → Obtener cliente por CI
PATCH  /api/customers/<ci>         → Actualizar datos del cliente
PATCH  /api/customers/<ci>/photos  → Subir fotos (multipart)
"""
from django.db import transaction
from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from core.models import Customer, CustomerReference
from core.api.serializers.customer import (
    CustomerCreateSerializer,
    CustomerUpdateSerializer,
    CustomerPhotoUploadSerializer,
    CustomerListQuerySerializer,
)
from core.api.security import require_roles, is_owner_admin


def _customer_to_dict(c: Customer, request=None) -> dict:
    """Serializa un Customer a dict para respuestas de API."""
    photo_face_url = None
    photo_ci_url   = None
    if c.photo_face:
        photo_face_url = request.build_absolute_uri(c.photo_face.url) if request else c.photo_face.url
    if c.photo_ci:
        photo_ci_url = request.build_absolute_uri(c.photo_ci.url) if request else c.photo_ci.url

    return {
        "public_id":           str(c.public_id),
        "ci":                  c.ci,
        "full_name":           c.full_name,
        "first_name":          c.first_name,
        "last_name_paternal":  c.last_name_paternal,
        "last_name_maternal":  c.last_name_maternal,
        "birth_date":          str(c.birth_date),
        "age":                 c.age,
        "phone":               c.phone,
        "email":               c.email,
        "address":             c.address,
        "gps_lat":             str(c.gps_lat) if c.gps_lat is not None else None,
        "gps_lon":             str(c.gps_lon) if c.gps_lon is not None else None,
        "photo_face_url":      photo_face_url,
        "photo_ci_url":        photo_ci_url,
        "is_blacklisted":      c.is_blacklisted,
        "blacklist_reason":    c.blacklist_reason,
        "category":            c.category,
        "score":               c.score,
        "risk_color":          c.risk_color,
        "total_contracts":     c.total_contracts,
        "late_payments_count": c.late_payments_count,
        "on_time_payments_count": c.on_time_payments_count,
        "references": [
            {
                "full_name":    r.full_name,
                "phone":        r.phone,
                "relationship": r.relationship,
            }
            for r in c.references.all()
        ],
        "created_at": c.created_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
class CustomerListCreateView(APIView):
    """
    GET  /api/customers  → Buscar/listar clientes
    POST /api/customers  → Crear nuevo cliente (KYC completo)
    """
    permission_classes = [IsAuthenticated]

    # ── Listar ────────────────────────────────────────────────────────────────
    def get(self, request):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        qs_ser = CustomerListQuerySerializer(data=request.query_params)
        qs_ser.is_valid(raise_exception=True)
        params = qs_ser.validated_data

        qs = Customer.objects.prefetch_related("references").order_by("-created_at")

        # Búsqueda por CI, nombre o apellido
        q = params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(ci__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name_paternal__icontains=q)
                | Q(last_name_maternal__icontains=q)
            )

        if "category" in params and params["category"]:
            qs = qs.filter(category=params["category"])

        if "is_blacklisted" in params:
            qs = qs.filter(is_blacklisted=params["is_blacklisted"])

        # Paginación simple
        page      = params["page"]
        page_size = params["page_size"]
        offset    = (page - 1) * page_size
        total     = qs.count()
        customers = qs[offset: offset + page_size]

        return Response({
            "total":     total,
            "page":      page,
            "page_size": page_size,
            "results":   [_customer_to_dict(c, request) for c in customers],
        })

    # ── Crear ─────────────────────────────────────────────────────────────────
    def post(self, request):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        # Aceptar datos de formulario (multipart) y JSON
        data = request.data
        serializer = CustomerCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        with transaction.atomic():
            customer = Customer.objects.create(
                ci                  = v["ci"],
                first_name          = v["first_name"],
                last_name_paternal  = v["last_name_paternal"],
                last_name_maternal  = v.get("last_name_maternal", ""),
                birth_date          = v["birth_date"],
                phone               = v["phone"],
                email               = v.get("email", ""),
                address             = v.get("address", ""),
                gps_lat             = v.get("gps_lat"),
                gps_lon             = v.get("gps_lon"),
                photo_face          = v.get("photo_face"),
                photo_ci            = v.get("photo_ci"),
                created_by          = request.user,
            )

            # Crear referencia si se proporcionó
            ref_name  = v.get("reference_name", "").strip()
            ref_phone = v.get("reference_phone", "").strip()
            if ref_name and ref_phone:
                CustomerReference.objects.create(
                    customer     = customer,
                    full_name    = ref_name,
                    phone        = ref_phone,
                    relationship = v.get("reference_relationship", ""),
                )

        return Response(_customer_to_dict(customer, request), status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
class CustomerDetailView(APIView):
    """
    GET   /api/customers/<ci>  → Obtener cliente (búsqueda por CI)
    PATCH /api/customers/<ci>  → Actualizar datos del cliente
    """
    permission_classes = [IsAuthenticated]

    def _get_customer(self, ci: str):
        try:
            return Customer.objects.prefetch_related("references").get(ci=ci.upper())
        except Customer.DoesNotExist:
            return None

    def get(self, request, ci):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        customer = self._get_customer(ci)
        if not customer:
            return Response({"detail": "Cliente no encontrado."}, status=404)
        return Response(_customer_to_dict(customer, request))

    def patch(self, request, ci):
        require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})
        customer = self._get_customer(ci)
        if not customer:
            return Response({"detail": "Cliente no encontrado."}, status=404)

        serializer = CustomerUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        # Cambiar lista negra solo si es OWNER_ADMIN o SUPERVISOR
        if "is_blacklisted" in v or "blacklist_reason" in v:
            require_roles(request.user, {"SUPERVISOR", "OWNER_ADMIN"})

        for field, value in v.items():
            setattr(customer, field, value)
        customer.save()

        return Response(_customer_to_dict(customer, request))


# ─────────────────────────────────────────────────────────────────────────────
class CustomerPhotoUploadView(APIView):
    """
    PATCH /api/customers/<ci>/photos
    Sube o reemplaza las fotos del cliente (multipart/form-data).
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, ci):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        try:
            customer = Customer.objects.get(ci=ci.upper())
        except Customer.DoesNotExist:
            return Response({"detail": "Cliente no encontrado."}, status=404)

        serializer = CustomerPhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        updated_fields = []
        if v.get("photo_face"):
            customer.photo_face = v["photo_face"]
            updated_fields.append("photo_face")
        if v.get("photo_ci"):
            customer.photo_ci = v["photo_ci"]
            updated_fields.append("photo_ci")

        if not updated_fields:
            return Response({"detail": "No se recibió ninguna foto."}, status=400)

        customer.save(update_fields=updated_fields + ["updated_at"])

        return Response({
            "detail":        "Fotos actualizadas.",
            "photo_face_url": request.build_absolute_uri(customer.photo_face.url) if customer.photo_face else None,
            "photo_ci_url":   request.build_absolute_uri(customer.photo_ci.url) if customer.photo_ci else None,
        })
