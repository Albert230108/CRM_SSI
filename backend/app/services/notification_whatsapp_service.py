import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.notification import Notification
from app.models.notification_whatsapp_delivery import NotificationWhatsappDelivery
from app.models.notification_whatsapp_trigger import NotificationWhatsappTrigger
from app.models.user import User
from app.services.whatsapp_client import WhatsAppBridgeError, send_system_whatsapp_message

MAX_ITEMIZED_NOTIFICATIONS = 10


def _debounce_seconds(db: Session) -> int:
    settings = db.query(AdminSettings).first()
    return settings.notification_whatsapp_debounce_seconds if settings is not None else 120


def register_notification_for_whatsapp(db: Session) -> None:
    """Called on every create_notification(), regardless of channel.

    Debounces the WhatsApp alert: resets the trigger timer on each call so a burst of
    notifications collapses into a single batched WhatsApp message once things go quiet, per
    the admin-configured `notification_whatsapp_debounce_seconds`. Does not commit - callers
    already own the surrounding transaction, matching create_notification.
    """
    trigger_at = datetime.now(timezone.utc) + timedelta(seconds=_debounce_seconds(db))
    trigger = db.query(NotificationWhatsappTrigger).first()
    if trigger is None:
        db.add(NotificationWhatsappTrigger(trigger_at=trigger_at))
    else:
        trigger.trigger_at = trigger_at


def _build_message(pending: list[Notification]) -> str:
    lines = [f"You have {len(pending)} new notification(s) in CRM_SSI:"]
    shown = pending[:MAX_ITEMIZED_NOTIFICATIONS]
    for notification in shown:
        tenant_name = notification.tenant_name or "Unknown tenant"
        preview = notification.preview or ""
        lines.append(f"- {tenant_name} ({notification.channel}): {preview}")
    remaining = len(pending) - len(shown)
    if remaining > 0:
        lines.append(f"+{remaining} more")
    return "\n".join(lines)


def flush_due_notification_whatsapp_batch(db: Session) -> None:
    """Consumes the due trigger (if any) and sends the batched WhatsApp alert.

    Always deletes the trigger row once handled, whether the batch was empty, fully sent, or
    partially failed - a permanently-broken recipient must not retry every cycle forever; a
    new notification will register a fresh trigger anyway.
    """
    now = datetime.now(timezone.utc)
    trigger = db.query(NotificationWhatsappTrigger).filter(NotificationWhatsappTrigger.trigger_at <= now).first()
    if trigger is None:
        return

    pending = (
        db.query(Notification)
        .filter(Notification.whatsapp_dispatched_at.is_(None))
        .order_by(Notification.event_at)
        .all()
    )
    if not pending:
        db.query(NotificationWhatsappTrigger).filter(NotificationWhatsappTrigger.id == trigger.id).delete()
        db.commit()
        return

    message = _build_message(pending)
    recipients = (
        db.query(User)
        .filter(User.whatsapp_notifications_enabled.is_(True), User.is_active.is_(True), User.phone.isnot(None))
        .all()
    )

    settings = db.query(AdminSettings).first()
    external_account_id = settings.notification_whatsapp_external_account_id if settings is not None else None

    for user in recipients:
        phone = (user.phone or "").strip()
        if not phone:
            continue
        try:
            asyncio.run(send_system_whatsapp_message(to=phone, message=message, external_account_id=external_account_id))
            db.add(
                NotificationWhatsappDelivery(
                    user_id=user.id, phone=phone, notification_count=len(pending), status="sent"
                )
            )
        except WhatsAppBridgeError as exc:
            db.add(
                NotificationWhatsappDelivery(
                    user_id=user.id,
                    phone=phone,
                    notification_count=len(pending),
                    status="failed",
                    error_message=str(exc)[:500],
                )
            )

    for notification in pending:
        notification.whatsapp_dispatched_at = now

    db.query(NotificationWhatsappTrigger).filter(NotificationWhatsappTrigger.id == trigger.id).delete()
    db.commit()
