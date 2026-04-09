"""
Comando de gestión: send_whatsapp_messages
===========================================
Worker que procesa la cola de mensajes WhatsApp pendientes y los envía
con técnicas de humanización para evitar bloqueos.

Estrategias anti-bloqueo implementadas:
  1. Solo envía en horario de oficina (8:00–18:00, L-V por defecto)
  2. Delay aleatorio entre 30 y 90 segundos entre mensajes
  3. Frase de cierre única y aleatoria en cada mensaje
  4. Límite de batch por ejecución (no envía todo el backlog de golpe)

Uso típico (cron diario a las 08:05):
  python manage.py send_whatsapp_messages

Opciones:
  --batch      Máximo de mensajes a enviar en esta ejecución (default: 50)
  --dry-run    Simula el envío sin llamar a la API ni dormir
  --force      Ignora la restricción de horario de oficina
  --delay-min  Segundos mínimos de espera entre mensajes (default: 30)
  --delay-max  Segundos máximos de espera entre mensajes (default: 90)
  --quiet      Solo imprime errores y el resumen final

Cron job recomendado (Linux):
  # Ejecutar a las 08:05 de lunes a viernes
  5 8 * * 1-5 /ruta/al/venv/bin/python /ruta/manage.py send_whatsapp_messages >> /var/log/whatsapp_worker.log 2>&1

Task Scheduler (Windows):
  Programa: C:\\ruta\\venv\\Scripts\\python.exe
  Argumentos: C:\\ruta\\manage.py send_whatsapp_messages
  Disparador: Diario 08:05, repetir cada 1 día
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import WhatsAppMessage
from core.services.whatsapp_sender import send_whatsapp_message
from core.services.whatsapp_humanizer import (
    humanize_message,
    is_office_hours,
    human_delay,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Envía los mensajes WhatsApp pendientes con humanización anti-bloqueo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch",
            type=int,
            default=50,
            help="Máximo de mensajes a enviar en esta ejecución (default: 50).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simula el envío sin llamar a la API ni esperar.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Ignora la restricción de horario de oficina.",
        )
        parser.add_argument(
            "--delay-min",
            type=int,
            default=None,
            help="Segundos mínimos entre mensajes (override de settings).",
        )
        parser.add_argument(
            "--delay-max",
            type=int,
            default=None,
            help="Segundos máximos entre mensajes (override de settings).",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            default=False,
            help="Solo imprime errores y el resumen final.",
        )

    def handle(self, *args, **options):
        dry_run   = options["dry_run"]
        force     = options["force"]
        quiet     = options["quiet"]
        batch     = options["batch"]
        delay_min = options["delay_min"]
        delay_max = options["delay_max"]

        now = timezone.localtime()

        # ── Guardia de horario ────────────────────────────────────────────────
        if not force and not is_office_hours(now):
            if not quiet:
                self.stdout.write(self.style.WARNING(
                    f"Fuera de horario de oficina ({now.strftime('%H:%M')}). "
                    "Usa --force para ignorar este control."
                ))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] No se enviarán mensajes reales."))

        # ── Obtener pendientes ────────────────────────────────────────────────
        pending = (
            WhatsAppMessage.objects
            .filter(
                status=WhatsAppMessage.Status.PENDING,
                scheduled_for__lte=now,
            )
            .select_related("customer", "contract")
            .order_by("scheduled_for")[:batch]
        )

        total_pending = pending.count()
        if total_pending == 0:
            if not quiet:
                self.stdout.write(self.style.SUCCESS("No hay mensajes pendientes."))
            return

        if not quiet:
            self.stdout.write(
                f"Procesando {total_pending} mensaje(s) "
                f"(batch={batch}, delay={delay_min or 'cfg'}-{delay_max or 'cfg'}s)..."
            )

        # ── Contadores ────────────────────────────────────────────────────────
        sent_ok  = 0
        failed   = 0
        total_wait = 0.0

        for i, msg in enumerate(pending, start=1):
            # Construir mensaje humanizado
            humanized_body = humanize_message(msg.message_body, now=now)

            if not quiet:
                preview = humanized_body[:80].replace("\n", " ")
                self.stdout.write(
                    f"[{i}/{total_pending}] {msg.event_type} → {msg.phone_to} | {preview}…"
                )

            if dry_run:
                # Solo simular
                delay = human_delay(delay_min, delay_max, dry_run=True)
                total_wait += delay
                sent_ok += 1
                if not quiet:
                    self.stdout.write(
                        self.style.SUCCESS(f"  [DRY-RUN OK] delay simulado: {delay}s")
                    )
                continue

            # ── Envío real ────────────────────────────────────────────────────
            result = send_whatsapp_message(
                phone_to=msg.phone_to,
                body=humanized_body,
            )

            if result["success"]:
                msg.status        = WhatsAppMessage.Status.SENT
                msg.wa_message_id = result["wa_message_id"]
                msg.sent_at       = timezone.now()
                msg.error_log     = ""
                msg.save(update_fields=["status", "wa_message_id", "sent_at", "error_log"])
                sent_ok += 1

                if not quiet:
                    self.stdout.write(
                        self.style.SUCCESS(f"  OK — wa_id: {result['wa_message_id']}")
                    )
            else:
                msg.status    = WhatsAppMessage.Status.FAILED
                msg.error_log = result["error"][:500]
                msg.save(update_fields=["status", "error_log"])
                failed += 1

                self.stdout.write(
                    self.style.ERROR(f"  FALLO — {result['error']}")
                )
                logger.error(
                    "WhatsApp envío fallido: msg_id=%s phone=%s error=%s",
                    msg.public_id, msg.phone_to, result["error"],
                )

            # ── Delay humanizado (excepto después del último mensaje) ─────────
            if i < total_pending:
                waited = human_delay(delay_min, delay_max, dry_run=False)
                total_wait += waited
                if not quiet:
                    self.stdout.write(f"  Esperando {waited:.1f}s antes del siguiente…")

        # ── Resumen final ─────────────────────────────────────────────────────
        summary = (
            f"Completado: {sent_ok} enviados, {failed} fallidos "
            f"| Tiempo total de espera: {total_wait:.0f}s"
            f"{' (dry-run)' if dry_run else ''}."
        )
        self.stdout.write(self.style.SUCCESS(summary))
        logger.info("WhatsApp worker: %s", summary)
