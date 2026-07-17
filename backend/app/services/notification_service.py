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
) -> Notification:
    """Persist a notification at message-ingestion time.

    Called directly from the WhatsApp/email inbound ingestion paths (not derived from
    polling), so history is durable and doesn't depend on a client being connected when the
    message arrives. Does not commit; callers already own the surrounding transaction.
    """
    notification = Notification(
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        channel=channel,
        direction=direction,
        preview=preview[:255] if preview else None,
    )
    db.add(notification)
    return notification
