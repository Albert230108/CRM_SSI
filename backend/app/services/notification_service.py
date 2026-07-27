from datetime import datetime

from sqlalchemy.orm import Session

from app.models.notification import Notification


def create_notification(
    db: Session,
    *,
    tenant_id: int,
    tenant_name: str | None,
    channel: str,
    direction: str,
    preview: str | None,
    event_at: datetime,
    thread_ref: str | None = None,
) -> Notification:
    """Persist a notification at message-ingestion time.

    Called directly from the WhatsApp/email inbound ingestion paths (not derived from
    polling), so history is durable and doesn't depend on a client being connected when the
    message arrives. Does not commit; callers already own the surrounding transaction.

    event_at is the message's own timestamp (Gmail internalDate, WhatsApp message time), not
    when this row is inserted — a delayed sync must not make an old message look brand new.
    """
    notification = Notification(
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        channel=channel,
        direction=direction,
        preview=preview[:255] if preview else None,
        event_at=event_at,
        thread_ref=thread_ref,
    )
    db.add(notification)
    return notification
