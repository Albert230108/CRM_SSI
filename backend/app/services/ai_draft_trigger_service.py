from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings


def _debounce_seconds(db: Session) -> int:
    settings = db.query(AdminSettings).first()
    return settings.ai_draft_debounce_seconds if settings is not None else 120


def register_inbound_message(
    db: Session,
    *,
    tenant: Tenant,
    channel: str,
    email_thread_id: int | None = None,
    whatsapp_endpoint_id: int | None = None,
) -> None:
    """Called on every genuinely-live inbound message (never for history/backfill replay).

    Debounces auto-draft generation: resets the trigger timer on each call so a burst of
    messages collapses into a single generation once the conversation goes quiet, per the
    admin-configured `ai_draft_debounce_seconds`. Also supersedes any not-yet-acted-on draft
    so a stale draft (generated before this message arrived) is never left sitting. Does not
    commit - callers already own the surrounding transaction, matching create_notification.
    """
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    auto_draft_enabled = (
        (ai_settings.auto_draft_email if channel == "email" else ai_settings.auto_draft_whatsapp)
        if ai_settings is not None
        else False
    )
    if not auto_draft_enabled:
        return

    db.query(AiAutoDraft).filter(
        AiAutoDraft.tenant_id == tenant.id,
        AiAutoDraft.channel == channel,
        AiAutoDraft.status.in_(["pending", "pending_auto_send"]),
    ).update({"status": "superseded"}, synchronize_session=False)

    trigger_at = datetime.now(timezone.utc) + timedelta(seconds=_debounce_seconds(db))
    existing_trigger = (
        db.query(AiAutoDraftTrigger)
        .filter(AiAutoDraftTrigger.tenant_id == tenant.id, AiAutoDraftTrigger.channel == channel)
        .first()
    )
    if existing_trigger is None:
        db.add(
            AiAutoDraftTrigger(
                tenant_id=tenant.id,
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
