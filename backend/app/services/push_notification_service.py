import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.models.device_token import DeviceToken
from app.models.notification import Notification
from app.models.notification_push_trigger import NotificationPushTrigger
from app.models.user import User

logger = logging.getLogger(__name__)

# Expo push service endpoint. Overridable for tests / self-hosting; no server secret is required
# (an optional EXPO_ACCESS_TOKEN is sent as a bearer if the project enables enhanced security).
EXPO_PUSH_API_URL = os.getenv("EXPO_PUSH_API_URL", "https://exp.host/--/api/v2/push/send")
_EXPO_BATCH_SIZE = 100


def _mask_token(token: str) -> str:
    """Redact an Expo push token for logs - keep enough to correlate, never the full value."""
    if len(token) <= 12:
        return "***"
    return f"{token[:12]}...{token[-4:]}"


def _debounce_seconds() -> int:
    try:
        return int(os.getenv("PUSH_NOTIFICATION_DEBOUNCE_SECONDS", "30"))
    except ValueError:
        return 30


def register_notification_for_push(db: Session) -> None:
    """Called on every create_notification(), regardless of channel.

    Debounces the push alert the same way the WhatsApp alert does: resets the single global
    trigger's timer on each call so a burst of notifications collapses into one push once things
    go quiet. Does not commit - callers already own the surrounding transaction, matching
    create_notification.
    """
    trigger_at = datetime.now(timezone.utc) + timedelta(seconds=_debounce_seconds())
    trigger = db.query(NotificationPushTrigger).first()
    if trigger is None:
        db.add(NotificationPushTrigger(trigger_at=trigger_at))
    else:
        trigger.trigger_at = trigger_at


def _build_push(pending: list[Notification]) -> tuple[str, str]:
    """Title/body for the batched push. `pending` is ordered by event_at ascending, so the last
    item is the most recent and drives the body preview."""
    count = len(pending)
    title = "New notification" if count == 1 else f"{count} new notifications"
    latest = pending[-1]
    tenant_name = latest.tenant_name or "Unknown tenant"
    preview = (latest.preview or "").strip()
    body = f"{tenant_name} ({latest.channel})"
    if preview:
        body = f"{body}: {preview}"
    return title, body[:180]


def _send_expo_batch(messages: list[dict]) -> list[dict]:
    """POST Expo push messages (chunked at 100) and return the aligned ticket list.

    Isolated so tests can stub it without any network I/O. Raises on transport/HTTP errors; the
    caller treats a raised/empty result as "sent nothing to prune".
    """
    if not messages:
        return []
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    access_token = os.getenv("EXPO_ACCESS_TOKEN")
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    tickets: list[dict] = []
    with httpx.Client(timeout=15.0) as http:
        for start in range(0, len(messages), _EXPO_BATCH_SIZE):
            chunk = messages[start : start + _EXPO_BATCH_SIZE]
            response = http.post(EXPO_PUSH_API_URL, json=chunk, headers=headers)
            response.raise_for_status()
            data = response.json().get("data", [])
            if isinstance(data, list):
                tickets.extend(data)
    return tickets


def flush_due_notification_push_batch(db: Session) -> None:
    """Consumes the due trigger (if any) and pushes the batched alert to every active user's
    registered devices.

    Always deletes the trigger and marks the batch's notifications push_dispatched once handled
    - whether the batch was empty, fully sent, or partially failed - so a permanently-broken
    device never makes the batch retry forever; a new notification registers a fresh trigger.
    Tokens Expo reports as DeviceNotRegistered are pruned.
    """
    now = datetime.now(timezone.utc)
    trigger = (
        db.query(NotificationPushTrigger)
        .filter(NotificationPushTrigger.trigger_at <= now)
        .first()
    )
    if trigger is None:
        return

    pending = (
        db.query(Notification)
        .filter(Notification.push_dispatched_at.is_(None))
        .order_by(Notification.event_at)
        .all()
    )
    if not pending:
        db.query(NotificationPushTrigger).filter(NotificationPushTrigger.id == trigger.id).delete()
        db.commit()
        return

    devices = (
        db.query(DeviceToken)
        .join(User, User.id == DeviceToken.user_id)
        .filter(User.is_active.is_(True))
        .all()
    )

    if devices:
        title, body = _build_push(pending)
        data: dict[str, object] = {"type": "notifications", "count": len(pending)}
        latest = pending[-1]
        if latest.tenant_id is not None:
            data["tenant_id"] = latest.tenant_id
        if latest.thread_ref is not None:
            data["thread_ref"] = latest.thread_ref
        messages = [
            {"to": device.token, "title": title, "body": body, "data": data, "sound": "default"}
            for device in devices
        ]
        try:
            tickets = _send_expo_batch(messages)
        except Exception:
            logger.exception("Expo push send failed")
            tickets = []

        ok_count = 0
        error_count = 0
        for device, ticket in zip(devices, tickets):
            if not isinstance(ticket, dict) or ticket.get("status") != "error":
                ok_count += 1
                continue
            error_count += 1
            details = ticket.get("details") or {}
            error_type = details.get("error") if isinstance(details, dict) else None
            if error_type == "DeviceNotRegistered":
                # Expected/self-healing: the token is dead, prune it quietly.
                db.delete(device)
            else:
                # Everything else (e.g. InvalidCredentials, MismatchSenderId) is a real
                # delivery failure - often a project-level misconfiguration affecting every
                # device - that must not be swallowed silently. Log it (token masked) so it's
                # diagnosable without a live probe.
                logger.error(
                    "Expo push rejected token=%s error=%s message=%s",
                    _mask_token(device.token),
                    error_type or "unknown",
                    ticket.get("message"),
                )
        if error_count:
            logger.warning(
                "Expo push batch: %d ok, %d error out of %d device(s)",
                ok_count,
                error_count,
                len(devices),
            )

    for notification in pending:
        notification.push_dispatched_at = now

    db.query(NotificationPushTrigger).filter(NotificationPushTrigger.id == trigger.id).delete()
    db.commit()
