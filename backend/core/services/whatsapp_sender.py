"""
Servicio de Envío WhatsApp — Meta Cloud API
=============================================
Encapsula la llamada HTTP a la API de Meta (v20.0).

Documentación oficial:
  https://developers.facebook.com/docs/whatsapp/cloud-api/messages/text-messages

Variables de entorno requeridas (en .env):
  WHATSAPP_TOKEN        → Bearer token de la app Meta Business
  WHATSAPP_PHONE_ID     → Phone number ID de la cuenta WA Business
  WHATSAPP_API_VERSION  → Versión de la API (default: v20.0)

Uso:
  from core.services.whatsapp_sender import send_whatsapp_message
  result = send_whatsapp_message(phone_to="+59170000000", body="Hola!")
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_API_VERSION = getattr(settings, "WHATSAPP_API_VERSION", "v20.0")
_BASE_URL    = "https://graph.facebook.com/{version}/{phone_id}/messages"


def _get_credentials() -> tuple[str, str]:
    """
    Retorna (token, phone_id).
    Lanza ValueError si faltan las variables de entorno.
    """
    token    = getattr(settings, "WHATSAPP_TOKEN", "")
    phone_id = getattr(settings, "WHATSAPP_PHONE_ID", "")

    if not token or not phone_id:
        raise ValueError(
            "Faltan las credenciales de WhatsApp. "
            "Configura WHATSAPP_TOKEN y WHATSAPP_PHONE_ID en el .env"
        )
    return token, phone_id


def send_whatsapp_message(phone_to: str, body: str) -> dict:
    """
    Envía un mensaje de texto libre a través de Meta Cloud API.

    Args:
        phone_to: Número en formato E.164 sin '+' (ej: "59170000000")
        body:     Texto del mensaje (máx. 4096 chars)

    Returns:
        {
            "success":    bool,
            "wa_message_id": str | "",   # ID devuelto por Meta
            "error":      str | "",      # descripción de error si success=False
            "raw":        dict,          # respuesta JSON completa de Meta
        }
    """
    # Normalizar número: quitar '+' si viene incluido
    phone_normalized = phone_to.lstrip("+")

    try:
        token, phone_id = _get_credentials()
    except ValueError as exc:
        logger.error("WhatsApp no configurado: %s", exc)
        return {"success": False, "wa_message_id": "", "error": str(exc), "raw": {}}

    url = _BASE_URL.format(version=_API_VERSION, phone_id=phone_id)

    payload = json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                phone_normalized,
        "type":              "text",
        "text": {
            "preview_url": False,
            "body":        body[:4096],
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            wa_id = (
                raw.get("messages", [{}])[0].get("id", "")
                if raw.get("messages") else ""
            )
            return {"success": True, "wa_message_id": wa_id, "error": "", "raw": raw}

    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            raw = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            raw = {"raw_body": body_bytes.decode("utf-8", errors="replace")}
        error_msg = raw.get("error", {}).get("message", str(exc))
        logger.error("WhatsApp HTTP error %s para %s: %s", exc.code, phone_to, error_msg)
        return {"success": False, "wa_message_id": "", "error": error_msg, "raw": raw}

    except Exception as exc:
        logger.error("WhatsApp error inesperado para %s: %s", phone_to, exc, exc_info=True)
        return {"success": False, "wa_message_id": "", "error": str(exc), "raw": {}}
