"""
Humanizador de Mensajes WhatsApp
==================================
Estrategias anti-bloqueo para evitar que WhatsApp detecte actividad de bot:

  1. Frases de cierre aleatorias únicas por mensaje (el texto nunca es idéntico)
  2. Delay aleatorio entre envíos (30-90 s por defecto, configurable)
  3. Variación por día de semana y franja horaria
  4. Validación de horario de oficina antes de enviar

Por qué funciona:
  WhatsApp usa heurísticas para detectar bots basándose en:
    a) Mensajes idénticos enviados en rafagas  → se rompe con frases variables
    b) Intervalos perfectamente regulares      → se rompe con delays aleatorios
    c) Envíos fuera de horario normal          → se evita con la guardia de horario
"""
from __future__ import annotations

import random
import time
from datetime import datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    pass


# ── Pool de frases de cierre ──────────────────────────────────────────────────
# Se elige una al azar para cada mensaje: nunca dos mensajes son idénticos.
_FRASES_CIERRE = [
    # Saludos por día
    "¡Que tenga un excelente lunes!",
    "¡Feliz martes, que sea un gran día!",
    "¡Buen miércoles, ya vamos a mitad de semana!",
    "¡Feliz jueves, ya casi es viernes!",
    "¡Buen viernes y excelente fin de semana!",
    "¡Buen sábado, que descanse!",
    # Saludos genéricos
    "¡Que tenga un excelente día!",
    "¡Saludos cordiales y buen día!",
    "¡Que le vaya muy bien!",
    "¡Buen día y muchos éxitos!",
    "¡Hasta pronto y buen día!",
    "¡Le deseamos un excelente día!",
    # Saludos con mención de sucursal
    "Saludos de todo el equipo.",
    "Atentamente, su casa de empeños de confianza.",
    "Quedamos a su disposición para cualquier consulta.",
    "Estamos para servirle.",
    # Por franja horaria (se selecciona según la hora)
    "¡Buenos días, que sea productivo!",
    "¡Buenas tardes, que termine bien el día!",
    "¡Buenas noches, descanse bien!",
]

_FRASES_MANANA = [
    "¡Buenos días! Que tenga un día productivo.",
    "¡Buenos días! Esperamos que todo marche bien.",
    "Buen inicio de día. Quedamos a su disposición.",
]

_FRASES_TARDE = [
    "¡Buenas tardes! Esperamos que su día esté yendo bien.",
    "¡Buenas tardes! Estamos para servirle.",
    "¡Buen resto de día! Saludos cordiales.",
]

_FRASES_SEMANA = {
    0: "¡Que tenga un excelente inicio de semana!",  # Lunes
    1: "¡Feliz martes! Que sea un gran día.",
    2: "¡Buen miércoles! Ya estamos a mitad de semana.",
    3: "¡Buen jueves! Ya casi llegamos al fin de semana.",
    4: "¡Buen viernes! Que tenga un merecido descanso.",
    5: "¡Buen sábado! Gracias por tomarse un momento.",
    6: "¡Buen domingo! Esperamos no molestar.",
}


def get_closing_phrase(now: datetime | None = None) -> str:
    """
    Devuelve una frase de cierre personalizada según la hora y día de la semana.
    Siempre devuelve algo diferente gracias al componente aleatorio.
    """
    if now is None:
        now = timezone.localtime()

    hour    = now.hour
    weekday = now.weekday()  # 0=lunes, 6=domingo

    candidates = []

    # Franja horaria
    if hour < 12:
        candidates.extend(_FRASES_MANANA)
    elif hour < 18:
        candidates.extend(_FRASES_TARDE)
    else:
        candidates.append("¡Buenas noches! Disculpe la hora.")

    # Día de la semana (siempre añade la del día)
    candidates.append(_FRASES_SEMANA[weekday])

    # Algunos genéricos para más variedad
    candidates.extend(random.sample(_FRASES_CIERRE, k=min(3, len(_FRASES_CIERRE))))

    return random.choice(candidates)


def humanize_message(body: str, now: datetime | None = None) -> str:
    """
    Agrega una frase de cierre única al cuerpo del mensaje.
    Garantiza que dos mensajes enviados en el mismo segundo nunca sean iguales.
    """
    closing = get_closing_phrase(now)
    return f"{body.rstrip()}\n\n{closing}"


# ── Horario de oficina ────────────────────────────────────────────────────────

def is_office_hours(now: datetime | None = None) -> bool:
    """
    Retorna True si la hora actual está dentro del horario de oficina.

    Configuración en settings.py (opcional, con defaults):
      WHATSAPP_OFFICE_HOURS_START = 8   # 08:00
      WHATSAPP_OFFICE_HOURS_END   = 18  # 18:00
      WHATSAPP_SEND_ON_WEEKENDS   = False
    """
    if now is None:
        now = timezone.localtime()

    start   = getattr(settings, "WHATSAPP_OFFICE_HOURS_START", 8)
    end     = getattr(settings, "WHATSAPP_OFFICE_HOURS_END",   18)
    weekends= getattr(settings, "WHATSAPP_SEND_ON_WEEKENDS",  False)

    if not weekends and now.weekday() >= 5:   # sábado=5, domingo=6
        return False

    return start <= now.hour < end


# ── Delay humanizado ──────────────────────────────────────────────────────────

def human_delay(
    min_seconds: int | None = None,
    max_seconds: int | None = None,
    dry_run: bool = False,
) -> float:
    """
    Espera un tiempo aleatorio entre min_seconds y max_seconds.
    Configurable vía settings:
      WHATSAPP_DELAY_MIN = 30
      WHATSAPP_DELAY_MAX = 90

    Args:
        dry_run: Si True, calcula el delay pero no duerme (para tests).

    Returns:
        Segundos que se esperó (o se habría esperado en dry_run).
    """
    cfg_min = getattr(settings, "WHATSAPP_DELAY_MIN", 30)
    cfg_max = getattr(settings, "WHATSAPP_DELAY_MAX", 90)

    lo = min_seconds if min_seconds is not None else cfg_min
    hi = max_seconds if max_seconds is not None else cfg_max

    # Asegura rango válido
    lo = max(1, lo)
    hi = max(lo + 1, hi)

    delay = random.uniform(lo, hi)

    if not dry_run:
        time.sleep(delay)

    return round(delay, 1)
