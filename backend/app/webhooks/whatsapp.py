from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.communication import Communication
from app.services.tenant_channel_resolver import resolve_tenant_for_inbound_channel

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhooks"])
logger = logging.getLogger(__name__)


def _first_text(payload: dict[str, Any]) -> str:
    for key in ("message", "text", "body", "content"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _pick_sender(payload: dict[str, Any]) -> str | None:
    for key in ("from", "sender", "phone", "wa_id", "phone_number"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _pick_timestamp(payload: dict[str, Any]) -> datetime:
    value = payload.get("timestamp") or payload.get("created_at") or payload.get("date")
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)) or str(value).isdigit():
        raw = int(value)
        if raw > 10**12:
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _secret_present(request: Request) -> bool:
    return bool(request.headers.get("X-Webhook-Secret") or request.query_params.get("secret") or request.query_params.get("webhook_secret") or request.headers.get("X-Webhook-Token"))


@router.post("")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"ok": False, "error": "Invalid webhook payload"})

    sender = _pick_sender(payload)
    provider = str(payload.get("provider") or request.headers.get("X-Provider") or "whatsapp-service").strip()
    external_account_id = str(payload.get("external_account_id") or payload.get("whatsapp_client_id") or request.headers.get("X-External-Account-Id") or "").strip()
    routing_result = resolve_tenant_for_inbound_channel(db, payload, dict(request.headers), dict(request.query_params))
    logger.info(
        "WhatsApp webhook received sender=%s provider=%s external_account_id=%s routing_strategy=%s secret_present=%s",
        sender,
        provider,
        external_account_id or None,
        routing_result.strategy,
        _secret_present(request),
    )

    tenant = routing_result.tenant
    if tenant is None:
        logger.warning("WhatsApp webhook tenant lookup failed strategy=%s sender=%s payload_keys=%s", routing_result.strategy, sender, sorted(list(payload.keys()))[:25])
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"ok": False, "error": "Tenant not found", "routing_strategy": routing_result.strategy})

    db.add(
        Communication(
            tenant_id=tenant.id,
            channel="whatsapp",
            direction="inbound",
            subject=payload.get("subject"),
            message=_first_text(payload),
            created_at=_pick_timestamp(payload),
        )
    )
    db.commit()
    return {"ok": True, "routing_strategy": routing_result.strategy}
