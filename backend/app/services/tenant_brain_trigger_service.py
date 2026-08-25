from datetime import datetime, timedelta, timezone

import logging

from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_brain_trigger import TenantBrainTrigger

logger = logging.getLogger(__name__)


def _debounce_seconds(db: Session) -> int:
    settings = db.query(AdminSettings).first()
    return settings.ai_draft_debounce_seconds if settings is not None else 120


def register_message_trigger(
    db: Session,
    *,
    tenant_id: int,
    channel: str,
    direction: str,
    email_thread_id: int | None = None,
    whatsapp_endpoint_id: int | None = None,
) -> None:
    """Called on every genuinely-live message, inbound or outbound, alongside
    ai_draft_trigger_service.register_inbound_message (which stays inbound-only - auto-draft
    generation is inherently a reply-to-inbound concept).

    Independent of auto_draft_*/planner_mode: gated purely on TenantAiSettings.brain_writer_enabled,
    so a tenant can build up a brain with AI replies fully off, and a tenant with AI replies on
    does not get brain-writing unless separately opted in. Debounces the same way the auto-draft
    trigger does, in its own queue. Does not commit - callers already own the transaction.

    `direction` isn't used for gating today (the brain writer reacts equally to either
    direction) - it documents intent and gives a future hook if that ever needs to change.
    """
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if ai_settings is None or not ai_settings.brain_writer_enabled:
        logger.info(f"Brain writer trigger skipped for tenant {tenant_id}: disabled/no settings")
        return

    trigger_at = datetime.now(timezone.utc) + timedelta(seconds=_debounce_seconds(db))
    existing_trigger = (
        db.query(TenantBrainTrigger)
        .filter(TenantBrainTrigger.tenant_id == tenant_id, TenantBrainTrigger.channel == channel)
        .first()
    )
    if existing_trigger is None:
        db.add(
            TenantBrainTrigger(
                tenant_id=tenant_id,
                channel=channel,
                trigger_at=trigger_at,
                email_thread_id=email_thread_id,
                whatsapp_endpoint_id=whatsapp_endpoint_id,
            )
        )
    else:
        existing_trigger.trigger_at = trigger_at
        if email_thread_id is not None:
            existing_trigger.email_thread_id = email_thread_id
        if whatsapp_endpoint_id is not None:
            existing_trigger.whatsapp_endpoint_id = whatsapp_endpoint_id

    logger.info(f"Brain writer trigger registered for tenant {tenant_id}, due at {trigger_at}")
