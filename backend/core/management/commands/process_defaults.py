"""
Comando de gestión: process_defaults
======================================
Procesa todos los contratos de empeño que superaron el período de gracia
y los marca automáticamente como DEFAULTED.

Uso típico (cron diario a las 00:05):
    python manage.py process_defaults

Modo de prueba (no persiste cambios):
    python manage.py process_defaults --dry-run

Opciones:
    --dry-run     Muestra qué contratos serían afectados sin guardar nada.
    --quiet       Solo imprime errores y el resumen final.
"""
from django.core.management.base import BaseCommand

from core.services.default_processor import mark_defaulted_contracts


class Command(BaseCommand):
    help = "Marca como DEFAULTED los contratos de empeño vencidos que superaron el período de gracia."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simula el proceso sin persistir cambios.",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            default=False,
            help="Muestra solo el resumen final.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        quiet   = options["quiet"]

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] No se guardarán cambios."))

        result = mark_defaulted_contracts(dry_run=dry_run)

        if not quiet:
            for row in result["contracts"]:
                status_icon = "[OK]"
                if "error" in row:
                    status_icon = "[ERROR]"

                line = (
                    f"{status_icon} {row['contract_number']}"
                    f" | venc: {row['due_date']}"
                    f" | {row['days_overdue']} días mora"
                    f" | scoring: {'si' if row.get('scoring_applied') else 'no'}"
                    f" | whatsapp: {'si' if row.get('whatsapp_queued') else 'no'}"
                )
                if "error" in row:
                    line += f" | ERROR: {row['error']}"
                    self.stdout.write(self.style.ERROR(line))
                else:
                    self.stdout.write(self.style.SUCCESS(line))

        summary = (
            f"Procesados: {result['processed']} contratos"
            f"{' (dry-run)' if dry_run else ''}."
        )
        self.stdout.write(self.style.SUCCESS(summary))
