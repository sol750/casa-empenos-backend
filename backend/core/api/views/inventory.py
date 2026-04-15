"""
Módulo de Inventario: Compra Directa (CD) y Vitrina.

Fase A – Adquisición (Cajero):
  POST /api/inventory/direct-purchase          → Crear CD
  POST /api/inventory/{id}/photos              → Subir fotos (mín. 3 requeridas)

Fase B – Valoración (Dueño):
  POST /api/inventory/{id}/price               → Fijar PVP y generar QR
  GET  /api/inventory/{id}/qr                  → Descargar QR (PNG)

Fase C – Venta (Cajero):
  POST /api/inventory/{id}/sell                → Registrar venta
  POST /api/inventory/{id}/cancel              → Cancelar artículo (OWNER_ADMIN)

Consultas:
  GET  /api/inventory                          → Listado con filtros
  GET  /api/inventory/{id}                     → Detalle
"""
import base64
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CashSession, CashMovement, Branch
from core.models_inventory import DirectPurchase, DirectPurchasePhoto
from core.api.security import require_roles, is_owner_admin, get_user_branch_codes

MIN_PHOTOS = 3


def _generate_qr_base64(data: str) -> str:
    """Genera un QR code como PNG base64."""
    import qrcode
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _serialize_purchase(p: DirectPurchase, include_qr=False) -> dict:
    photos = [
        {
            "photo_id":    str(ph.public_id),
            "url":         ph.photo.url if ph.photo else None,
            "uploaded_at": ph.uploaded_at,
        }
        for ph in p.photos.all()
    ]
    data = {
        "purchase_id":            str(p.public_id),
        "branch_code":            p.branch.code,
        "status":                 p.status,
        "category":               p.category,
        "description":            p.description,
        "attributes":             p.attributes,
        "market_value_estimate":  str(p.market_value_estimate) if p.market_value_estimate else None,
        "suggested_mvi":          str(p.suggested_mvi) if p.suggested_mvi else None,
        "purchase_price":         str(p.purchase_price),
        "pvp":                    str(p.pvp) if p.pvp else None,
        "projected_profit":       str(p.projected_profit) if p.projected_profit else None,
        "sale_price":             str(p.sale_price) if p.sale_price else None,
        "actual_profit":          str(p.actual_profit) if p.actual_profit else None,
        "photos":                 photos,
        "photos_count":           len(photos),
        "purchase_date":          str(p.purchase_date) if p.purchase_date else None,
        "created_at":             p.created_at,
        "priced_at":              p.priced_at,
        "sold_at":                p.sold_at,
    }
    if include_qr and p.qr_code_data:
        data["qr_base64"] = _generate_qr_base64(p.qr_code_data)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# LISTADO
# ─────────────────────────────────────────────────────────────────────────────
class InventoryListView(APIView):
    """GET /api/inventory  —  Filtros: ?status=, ?branch=, ?category="""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        qs = DirectPurchase.objects.select_related("branch").prefetch_related("photos").order_by("-created_at")

        if not is_owner_admin(request.user):
            allowed = get_user_branch_codes(request.user)
            qs = qs.filter(branch__code__in=allowed)

        if s := request.query_params.get("status"):
            qs = qs.filter(status=s.upper())
        if b := request.query_params.get("branch"):
            qs = qs.filter(branch__code=b.upper())
        if c := request.query_params.get("category"):
            qs = qs.filter(category=c.upper())

        return Response({
            "count":   qs.count(),
            "results": [_serialize_purchase(p) for p in qs[:200]],
        })


# ─────────────────────────────────────────────────────────────────────────────
# DETALLE
# ─────────────────────────────────────────────────────────────────────────────
class InventoryDetailView(APIView):
    """GET /api/inventory/{id}"""
    permission_classes = [IsAuthenticated]

    def get(self, request, purchase_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})
        try:
            p = DirectPurchase.objects.select_related("branch").prefetch_related("photos").get(
                public_id=purchase_id
            )
        except DirectPurchase.DoesNotExist:
            return Response({"detail": "Artículo no encontrado."}, status=404)

        if not is_owner_admin(request.user):
            if p.branch.code not in get_user_branch_codes(request.user):
                return Response({"detail": "Sin acceso a esta sucursal."}, status=403)

        return Response(_serialize_purchase(p))


# ─────────────────────────────────────────────────────────────────────────────
# FASE A — Crear Compra Directa
# ─────────────────────────────────────────────────────────────────────────────
class DirectPurchaseCreateView(APIView):
    """POST /api/inventory/direct-purchase"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        required = ["cash_session_id", "category", "description", "purchase_price"]
        for f in required:
            if not request.data.get(f):
                return Response({"detail": f"Campo requerido: {f}"}, status=400)

        try:
            cash_session = CashSession.objects.select_related(
                "cash_register", "branch"
            ).get(public_id=request.data["cash_session_id"])
        except CashSession.DoesNotExist:
            return Response({"detail": "Sesión de caja no encontrada."}, status=404)

        if cash_session.status != CashSession.Status.OPEN:
            return Response({"detail": "La sesión de caja no está abierta."}, status=409)

        try:
            purchase_price = Decimal(str(request.data["purchase_price"]))
            if purchase_price <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return Response({"detail": "purchase_price debe ser mayor a 0."}, status=400)

        mve_raw = request.data.get("market_value_estimate")
        market_value_estimate = Decimal(str(mve_raw)) if mve_raw else None

        # Fase de Sincronización: purchase_date / effective_date
        purchase_date = None
        effective_date = None
        raw_pd = request.data.get("purchase_date") or request.data.get("effective_date")
        if raw_pd:
            try:
                purchase_date = date.fromisoformat(str(raw_pd))
            except ValueError:
                return Response({"detail": "purchase_date debe estar en formato YYYY-MM-DD."}, status=400)
            if purchase_date > timezone.now().date():
                return Response({"detail": "purchase_date no puede ser futura."}, status=400)
            effective_date = purchase_date

        with transaction.atomic():
            purchase = DirectPurchase.objects.create(
                branch                 = cash_session.branch,
                cash_session           = cash_session,
                created_by             = request.user,
                category               = request.data["category"].upper(),
                description            = request.data["description"],
                attributes             = request.data.get("attributes", {}),
                market_value_estimate  = market_value_estimate,
                purchase_price         = purchase_price,
                purchase_date          = purchase_date,
            )

            # Movimiento de caja: salida de dinero (CD); retroactivo si purchase_date != hoy
            CashMovement.objects.create(
                cash_session   = cash_session,
                cash_register  = cash_session.cash_register,
                branch         = cash_session.branch,
                movement_type  = CashMovement.MovementType.PURCHASE_OUT,
                amount         = purchase_price,
                performed_by   = request.user,
                note           = f"CD – Compra directa {purchase.public_id}",
                effective_date = effective_date,
            )

        return Response(
            {
                "detail":           "Artículo registrado como Compra Directa.",
                "purchase_id":      str(purchase.public_id),
                "status":           purchase.status,
                "purchase_price":   str(purchase.purchase_price),
                "suggested_mvi":    str(purchase.suggested_mvi) if purchase.suggested_mvi else None,
                "next_step":        f"Sube al menos {MIN_PHOTOS} fotos: POST /api/inventory/{purchase.public_id}/photos",
            },
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# FASE A — Subir fotos
# ─────────────────────────────────────────────────────────────────────────────
class InventoryPhotoUploadView(APIView):
    """POST /api/inventory/{id}/photos  —  multipart, campo: photo"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, purchase_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        try:
            purchase = DirectPurchase.objects.select_related("branch").get(public_id=purchase_id)
        except DirectPurchase.DoesNotExist:
            return Response({"detail": "Artículo no encontrado."}, status=404)

        if purchase.status not in (
            DirectPurchase.Status.COMPRADO_PENDIENTE,
            DirectPurchase.Status.EN_VENTA,
        ):
            return Response({"detail": "No se pueden agregar fotos en este estado."}, status=409)

        files = request.FILES.getlist("photo")
        if not files:
            return Response({"detail": "Se requiere al menos un archivo en el campo 'photo'."}, status=400)

        created = []
        for f in files:
            photo = DirectPurchasePhoto.objects.create(
                purchase    = purchase,
                photo       = f,
                uploaded_by = request.user,
            )
            created.append(str(photo.public_id))

        total = purchase.photos.count()
        return Response({
            "detail":        f"{len(created)} foto(s) subida(s).",
            "photos_added":  created,
            "total_photos":  total,
            "ready_for_pricing": total >= MIN_PHOTOS,
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# FASE B — Fijar precio y generar QR (Dueño)
# ─────────────────────────────────────────────────────────────────────────────
class InventoryPriceView(APIView):
    """POST /api/inventory/{id}/price  —  Body: { "pvp": 850 }"""
    permission_classes = [IsAuthenticated]

    def post(self, request, purchase_id):
        require_roles(request.user, {"OWNER_ADMIN"})

        try:
            purchase = DirectPurchase.objects.prefetch_related("photos").get(public_id=purchase_id)
        except DirectPurchase.DoesNotExist:
            return Response({"detail": "Artículo no encontrado."}, status=404)

        if purchase.status != DirectPurchase.Status.COMPRADO_PENDIENTE:
            return Response(
                {"detail": f"El artículo ya está en estado {purchase.status}, no se puede fijar precio."},
                status=409,
            )

        # Validar mínimo de fotos
        photo_count = purchase.photos.count()
        if photo_count < MIN_PHOTOS:
            return Response(
                {"detail": f"Se requieren mínimo {MIN_PHOTOS} fotos. Hay {photo_count} subida(s)."},
                status=409,
            )

        pvp_raw = request.data.get("pvp")
        if not pvp_raw:
            return Response({"detail": "Se requiere pvp (precio de vitrina)."}, status=400)

        try:
            pvp = Decimal(str(pvp_raw))
            if pvp <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return Response({"detail": "pvp debe ser mayor a 0."}, status=400)

        projected_profit = (pvp - purchase.purchase_price).quantize(Decimal("0.01"))

        # QR data = URL canónica del artículo (el frontend imprime el QR)
        qr_data = f"inv:{purchase.public_id}"

        with transaction.atomic():
            purchase.pvp              = pvp
            purchase.projected_profit = projected_profit
            purchase.priced_by        = request.user
            purchase.priced_at        = timezone.now()
            purchase.qr_code_data     = qr_data
            purchase.status           = DirectPurchase.Status.EN_VENTA
            purchase.save(update_fields=[
                "pvp", "projected_profit", "priced_by", "priced_at",
                "qr_code_data", "status",
            ])

        # Generar QR como base64 PNG
        qr_base64 = _generate_qr_base64(qr_data)

        return Response({
            "detail":            "Precio fijado. Artículo en vitrina.",
            "purchase_id":       str(purchase.public_id),
            "status":            purchase.status,
            "purchase_price":    str(purchase.purchase_price),
            "pvp":               str(pvp),
            "projected_profit":  str(projected_profit),
            "qr_data":           qr_data,
            "qr_base64_png":     qr_base64,
        })


# ─────────────────────────────────────────────────────────────────────────────
# FASE B — Endpoint QR independiente (para re-imprimir)
# ─────────────────────────────────────────────────────────────────────────────
class InventoryQRView(APIView):
    """GET /api/inventory/{id}/qr"""
    permission_classes = [IsAuthenticated]

    def get(self, request, purchase_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        try:
            purchase = DirectPurchase.objects.get(public_id=purchase_id)
        except DirectPurchase.DoesNotExist:
            return Response({"detail": "Artículo no encontrado."}, status=404)

        if not purchase.qr_code_data:
            return Response(
                {"detail": "El artículo aún no tiene QR generado. Fije el precio primero."},
                status=409,
            )

        qr_base64 = _generate_qr_base64(purchase.qr_code_data)
        return Response({
            "purchase_id":   str(purchase.public_id),
            "qr_data":       purchase.qr_code_data,
            "qr_base64_png": qr_base64,
            "pvp":           str(purchase.pvp) if purchase.pvp else None,
            "description":   purchase.description,
        })


# ─────────────────────────────────────────────────────────────────────────────
# FASE C — Registrar venta
# ─────────────────────────────────────────────────────────────────────────────
class InventorySellView(APIView):
    """
    POST /api/inventory/{id}/sell
    Body: { "cash_session_id": "uuid", "sale_price": 800, "note": "" }
    Acepta escaneo por QR: el frontend envía el purchase_id extraído del QR.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, purchase_id):
        require_roles(request.user, {"CAJERO", "SUPERVISOR", "OWNER_ADMIN"})

        try:
            purchase = DirectPurchase.objects.select_related("branch").get(public_id=purchase_id)
        except DirectPurchase.DoesNotExist:
            return Response({"detail": "Artículo no encontrado."}, status=404)

        if purchase.status != DirectPurchase.Status.EN_VENTA:
            return Response(
                {"detail": f"El artículo no está en vitrina. Estado actual: {purchase.status}"},
                status=409,
            )

        if not is_owner_admin(request.user):
            if purchase.branch.code not in get_user_branch_codes(request.user):
                return Response({"detail": "Sin acceso a esta sucursal."}, status=403)

        required = ["cash_session_id", "sale_price"]
        for f in required:
            if not request.data.get(f):
                return Response({"detail": f"Campo requerido: {f}"}, status=400)

        try:
            sale_price = Decimal(str(request.data["sale_price"]))
            if sale_price <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return Response({"detail": "sale_price debe ser mayor a 0."}, status=400)

        try:
            cash_session = CashSession.objects.select_related(
                "cash_register", "branch"
            ).get(public_id=request.data["cash_session_id"])
        except CashSession.DoesNotExist:
            return Response({"detail": "Sesión de caja no encontrada."}, status=404)

        if cash_session.status != CashSession.Status.OPEN:
            return Response({"detail": "La sesión de caja no está abierta."}, status=409)

        actual_profit = (sale_price - purchase.purchase_price).quantize(Decimal("0.01"))
        note = request.data.get("note", "")

        with transaction.atomic():
            # Movimiento de caja: entrada de dinero (V – Venta)
            CashMovement.objects.create(
                cash_session  = cash_session,
                cash_register = cash_session.cash_register,
                branch        = cash_session.branch,
                movement_type = CashMovement.MovementType.PAYMENT_IN,
                amount        = sale_price,
                performed_by  = request.user,
                note          = f"V – Venta CD {purchase.public_id} | UV={actual_profit} Bs",
            )

            purchase.status            = DirectPurchase.Status.VENDIDO
            purchase.sale_cash_session = cash_session
            purchase.sold_by           = request.user
            purchase.sold_at           = timezone.now()
            purchase.sale_price        = sale_price
            purchase.actual_profit     = actual_profit
            purchase.save(update_fields=[
                "status", "sale_cash_session", "sold_by",
                "sold_at", "sale_price", "actual_profit",
            ])

        return Response({
            "detail":          "Venta registrada. Artículo marcado como VENDIDO.",
            "purchase_id":     str(purchase.public_id),
            "sale_price":      str(sale_price),
            "purchase_price":  str(purchase.purchase_price),
            "actual_profit":   str(actual_profit),
            "sold_at":         purchase.sold_at,
        })


# ─────────────────────────────────────────────────────────────────────────────
# CANCELAR artículo (Dueño)
# ─────────────────────────────────────────────────────────────────────────────
class InventoryCancelView(APIView):
    """POST /api/inventory/{id}/cancel"""
    permission_classes = [IsAuthenticated]

    def post(self, request, purchase_id):
        require_roles(request.user, {"OWNER_ADMIN"})

        try:
            purchase = DirectPurchase.objects.get(public_id=purchase_id)
        except DirectPurchase.DoesNotExist:
            return Response({"detail": "Artículo no encontrado."}, status=404)

        if purchase.status == DirectPurchase.Status.VENDIDO:
            return Response({"detail": "No se puede cancelar un artículo ya vendido."}, status=409)

        purchase.status = DirectPurchase.Status.CANCELADO
        purchase.save(update_fields=["status"])

        return Response({
            "detail":      "Artículo cancelado.",
            "purchase_id": str(purchase.public_id),
        })
