import base64
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.gmail_integration import _process_gmail_history_notification
from app.core.dependencies import get_db
from app.models.gmail_integration import GmailAccount

router = APIRouter(prefix="/webhooks/gmail", tags=["gmail-webhooks"])
logger = logging.getLogger(__name__)


def _is_authorized(request: Request) -> bool:
    expected_secret = os.getenv("GMAIL_PUBSUB_WEBHOOK_SECRET", "")
    if not expected_secret:
        logger.error("GMAIL_PUBSUB_WEBHOOK_SECRET is not configured")
        return False
    provided_secret = request.query_params.get("token", "")
    return hmac.compare_digest(provided_secret, expected_secret)


def _decode_notification(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Decode a Pub/Sub push envelope into (email_address, history_id), or None if unparseable."""
    message = payload.get("message") or {}
    data = message.get("data")
    if not data:
        return None
    try:
        decoded = base64.b64decode(data).decode("utf-8")
        notification = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    email_address = notification.get("emailAddress")
    history_id = notification.get("historyId")
    if not email_address or history_id is None:
        return None
    return str(email_address).strip().lower(), str(history_id)


def _handle_notification(db: Session, email_address: str, history_id: str) -> None:
    account = (
        db.query(GmailAccount)
        .filter(GmailAccount.email_address == email_address)
        .filter(GmailAccount.is_active.is_(True))
        .first()
    )
    if account is None:
        logger.info("Gmail push notification for unknown/inactive account email=%s", email_address)
        return
    _process_gmail_history_notification(db, account, history_id)


@router.post("")
async def gmail_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not _is_authorized(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    try:
        payload = await request.json()
    except ValueError as exc:
        # A malformed/non-JSON body raised json.JSONDecodeError straight out as a 500; return 400.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")

    decoded = _decode_notification(payload)
    if decoded is None:
        logger.warning("Gmail webhook received an unparseable notification payload")
        return {"ok": False, "detail": "unparseable notification"}

    email_address, history_id = decoded
    try:
        await run_in_threadpool(_handle_notification, db, email_address, history_id)
    except HttpError as exc:
        # account.last_history_id is only advanced on success (see _process_gmail_history_
        # notification), so returning 200 here without raising is safe: it never loses data,
        # it just defers it to the next successful push or the scheduled catch-up poll.
        # Letting this propagate as a 500 instead would make Pub/Sub redeliver the same
        # notification immediately, re-hitting the same exhausted rate limit and compounding
        # the 429 storm this handler exists to avoid.
        upstream_status = exc.resp.status if exc.resp is not None else None
        logger.warning(
            "Gmail webhook processing failed with upstream error email=%s history_id=%s status=%s",
            email_address,
            history_id,
            upstream_status,
        )
        db.rollback()
        return {"ok": False, "detail": "gmail upstream error, will retry via next notification or scheduled catch-up"}
    except Exception:
        logger.exception("Gmail webhook processing failed email=%s history_id=%s", email_address, history_id)
        db.rollback()
        return {"ok": False, "detail": "processing failed, will retry via next notification or scheduled catch-up"}
    return {"ok": True}
