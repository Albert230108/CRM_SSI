from datetime import datetime, timedelta, timezone

import logging

from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.action_writer_trigger import ActionWriterTrigger
from app.models.communication import Communication
from app.models.tenant_ai_settings import TenantAiSettings

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
    """Called on every genuinely-live message, inbound or outbound - mirrors
    tenant_brain_trigger_service.register_message_trigger in its own debounce queue.

    Gated purely on TenantAiSettings.action_writer_enabled, independent of brain_writer_enabled
    and planner_mode. Does not commit - callers already own the transaction.

    `direction` isn't used for gating today (the action writer reacts equally to either
    direction) - it documents intent and gives a future hook if that ever needs to change.
    """
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if ai_settings is None or not ai_settings.action_writer_enabled:
        logger.info(f"Action writer trigger skipped for tenant {tenant_id}: disabled/no settings")
        return

    trigger_at = datetime.now(timezone.utc) + timedelta(seconds=_debounce_seconds(db))
    existing_trigger = (
        db.query(ActionWriterTrigger)
        .filter(ActionWriterTrigger.tenant_id == tenant_id, ActionWriterTrigger.channel == channel)
        .first()
    )
    if existing_trigger is None:
        db.add(
            ActionWriterTrigger(
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

    logger.info(f"Action writer trigger registered for tenant {tenant_id}, due at {trigger_at}")


def register_manual_trigger(db: Session, *, tenant_id: int) -> bool:
    """Register an immediate action-writer trigger after a manual brain scan update.

    The scan endpoint is already async from the user's perspective, so we reuse the existing
    sweep loop but schedule the trigger for the next tick instead of waiting for the live-message
    debounce. Returns True when a trigger row was created or updated.
    """
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if ai_settings is None or not ai_settings.action_writer_enabled:
        logger.info(f"Action writer manual trigger skipped for tenant {tenant_id}: disabled/no settings")
        return False

    latest_communication = (
        db.query(Communication)
        .filter(Communication.tenant_id == tenant_id)
        .order_by(Communication.created_at.desc(), Communication.id.desc())
        .first()
    )
    if latest_communication is None:
        logger.info(f"Action writer manual trigger skipped for tenant {tenant_id}: no communications yet")
        return False

    trigger_at = datetime.now(timezone.utc)
    existing_trigger = (
        db.query(ActionWriterTrigger)
        .filter(ActionWriterTrigger.tenant_id == tenant_id, ActionWriterTrigger.channel == latest_communication.channel)
        .first()
    )
    if existing_trigger is None:
        db.add(ActionWriterTrigger(tenant_id=tenant_id, channel=latest_communication.channel, trigger_at=trigger_at))
    else:
        existing_trigger.trigger_at = trigger_at

    logger.info(
        "Action writer manual trigger registered for tenant %s, channel %s, due at %s",
        tenant_id,
        latest_communication.channel,
        trigger_at,
    )
    return True
