"""
Serializadores del Módulo Cliente
"""
from rest_framework import serializers
from core.models import Customer, CustomerReference


# ── Referencia de cliente ──────────────────────────────────────────────────────
class CustomerReferenceReadSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CustomerReference
        fields = ["id", "full_name", "phone", "relationship"]


# ── Creación de cliente ────────────────────────────────────────────────────────
class CustomerCreateSerializer(serializers.Serializer):
    # Identidad KYC
    ci                  = serializers.CharField(max_length=30)
    first_name          = serializers.CharField(max_length=80)
    last_name_paternal  = serializers.CharField(max_length=80)
    last_name_maternal  = serializers.CharField(max_length=80, required=False, default="", allow_blank=True)
    birth_date          = serializers.DateField()

    # Fotos (opcionales al crear; se suben vía PATCH después si se prefiere)
    photo_face = serializers.ImageField(required=False, allow_null=True)
    photo_ci   = serializers.ImageField(required=False, allow_null=True)

    # Contacto
    phone   = serializers.CharField(max_length=20)
    email   = serializers.EmailField(required=False, default="", allow_blank=True)
    address = serializers.CharField(required=False, default="", allow_blank=True)
    gps_lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    gps_lon = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)

    # Referencia personal (opcional, crea un CustomerReference asociado)
    reference_name         = serializers.CharField(max_length=120, required=False, default="", allow_blank=True)
    reference_phone        = serializers.CharField(max_length=20,  required=False, default="", allow_blank=True)
    reference_relationship = serializers.CharField(max_length=60,  required=False, default="", allow_blank=True)

    def validate_ci(self, value):
        if Customer.objects.filter(ci=value).exists():
            raise serializers.ValidationError("Ya existe un cliente con esta CI.")
        return value.strip().upper()

    def validate_birth_date(self, value):
        from datetime import date
        today = date.today()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 18:
            raise serializers.ValidationError("El cliente debe ser mayor de 18 años.")
        return value


# ── Actualización parcial ──────────────────────────────────────────────────────
class CustomerUpdateSerializer(serializers.Serializer):
    first_name         = serializers.CharField(max_length=80,  required=False)
    last_name_paternal = serializers.CharField(max_length=80,  required=False)
    last_name_maternal = serializers.CharField(max_length=80,  required=False, allow_blank=True)
    birth_date         = serializers.DateField(required=False)
    phone              = serializers.CharField(max_length=20,  required=False)
    email              = serializers.EmailField(required=False, allow_blank=True)
    address            = serializers.CharField(required=False, allow_blank=True)
    gps_lat            = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    gps_lon            = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    # Solo OWNER_ADMIN/SUPERVISOR puede modificar lista negra
    is_blacklisted   = serializers.BooleanField(required=False)
    blacklist_reason = serializers.CharField(required=False, allow_blank=True)


# ── Subida de fotos (multipart independiente) ──────────────────────────────────
class CustomerPhotoUploadSerializer(serializers.Serializer):
    photo_face = serializers.ImageField(required=False, allow_null=True)
    photo_ci   = serializers.ImageField(required=False, allow_null=True)


# ── Query params para listado ──────────────────────────────────────────────────
class CustomerListQuerySerializer(serializers.Serializer):
    q              = serializers.CharField(required=False, allow_blank=True,
                                           help_text="Buscar por CI, nombre o apellido")
    category       = serializers.ChoiceField(choices=Customer.Category.choices, required=False)
    is_blacklisted = serializers.BooleanField(required=False)
    page           = serializers.IntegerField(min_value=1, default=1)
    page_size      = serializers.IntegerField(min_value=1, max_value=100, default=20)
