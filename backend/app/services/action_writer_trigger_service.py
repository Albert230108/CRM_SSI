from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.action_writer_trigger import ActionWriterTrigger
from app.models.tenant_ai_settings import TenantAiSettings


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
