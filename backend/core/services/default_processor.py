"""
Procesador de Mora Automática
==============================
Identifica contratos ACTIVE cuya due_date + grace_period_days ya pasó
y los marca como DEFAULTED.

Flujo:
  1. Buscar contratos ACTIVE donde due_date + grace_period_days <= hoy
  2. Marcar status=DEFAULTED, defaulted_at=now
  3. Aplicar penalización de scoring al cliente vinculado
  4. Encolar aviso WhatsApp OVERDUE_NOTICE (si tiene cliente)
  5. Devolver resumen con lista de contratos procesados

Uso:
  from core.services.default_processor import mark_defaulted_contracts
  result = mark_defaulted_contracts()
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def mark_defaulted_contracts(dry_run: bool = False) -> dict:
    """
    Procesa todos los contratos que entraron en mora.

    Args:
        dry_run: Si True, calcula pero NO persiste ningún cambio.

    Returns:
        {
            "processed": int,
            "dry_run": bool,
            "contracts": [
                {
                    "contract_number": str,
                    "customer_ci": str,
                    "due_date": str,
                    "days_overdue": int,
                    "scoring_applied": bool,
                    "whatsapp_queued": bool,
                }
            ]
        }
    """
    from core.models import PawnContract, WhatsAppMessage
    from core.services.scoring_engine import apply_default_penalty

    today = date.today()
    results = []

    # Traemos todos los contratos ACTIVE con su sucursal y cliente
    candidates = (
        PawnContract.objects
        .select_related("branch", "customer")
        .filter(status=PawnContract.Status.ACTIVE)
    )

    to_default = []
    for contract in candidates:
        grace = contract.branch.grace_period_days
        cutoff = contract.due_date + timedelta(days=grace)
        if today > cutoff:
            to_default.append((contract, (today - contract.due_date).days))

    if not to_default:
        return {"processed": 0, "dry_run": dry_run, "contracts": []}

    for contract, days_overdue in to_default:
        row = {
            "contract_number": contract.contract_number,
            "customer_ci":     contract.customer_ci or "",
            "due_date":        str(contract.due_date),
            "days_overdue":    days_overdue,
            "scoring_applied": False,
            "whatsapp_queued": False,
        }

        if dry_run:
            results.append(row)
            continue

        try:
            with transaction.atomic():
                # 1) Marcar en mora
                contract.status = PawnContract.Status.DEFAULTED
                contract.defaulted_at = timezone.now()
                contract.save(update_fields=["status", "defaulted_at"])

                # 2) Penalización de scoring
                scoring_result = apply_default_penalty(contract)
                row["scoring_applied"] = scoring_result.get("applied", False)

                # 3) WhatsApp OVERDUE_NOTICE
                if contract.customer and contract.customer.phone:
                    from django.utils import timezone as tz
                    body = (
                        f"Hola {contract.customer.first_name}, tu contrato "
                        f"#{contract.contract_number} tiene {days_overdue} día(s) de mora "
                        f"(vencía {contract.due_date.strftime('%d/%m/%Y')}). "
                        f"Capital: Bs.{contract.principal_amount:,}. "
                        f"Por favor acércate a regularizar. ¡Gracias!"
                    )
                    WhatsAppMessage.objects.create(
                        customer      = contract.customer,
                        contract      = contract,
                        event_type    = WhatsAppMessage.EventType.OVERDUE_NOTICE,
                        phone_to      = contract.customer.phone,
                        message_body  = body,
                        scheduled_for = tz.now(),
                    )
                    row["whatsapp_queued"] = True

            results.append(row)

        except Exception as exc:
            logger.error(
                "Error procesando mora del contrato %s: %s",
                contract.contract_number,
                exc,
                exc_info=True,
            )
            row["error"] = str(exc)
            results.append(row)

    return {
        "processed": len([r for r in results if "error" not in r]),
        "dry_run":   dry_run,
        "contracts": results,
    }
