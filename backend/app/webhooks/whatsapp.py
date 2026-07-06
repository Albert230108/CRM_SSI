from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.phone_normalization import phone_match_candidates
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.services.tenant_channel_resolver import resolve_tenant_for_inbound_channel

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhooks"])
logger = logging.getLogger(__name__)


class WhatsAppWebhookResponse(BaseModel):
    ok: bool
    routing_strategy: str | None = None
    tenant_id: int | None = None
    message: str | None = None


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


def _pick_recipient(payload: dict[str, Any]) -> str | None:
    for key in ("to", "recipient", "phone_number", "whatsapp_chat_id"):
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


@router.post("", response_model=WhatsAppWebhookResponse)
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)) -> WhatsAppWebhookResponse | JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"ok": False, "error": "Invalid webhook payload"})

    sender = _pick_sender(payload)
    recipient = _pick_recipient(payload)
    provider = str(payload.get("provider") or request.headers.get("X-Provider") or "whatsapp-service").strip()
    external_account_id = str(payload.get("external_account_id") or payload.get("whatsapp_client_id") or request.headers.get("X-External-Account-Id") or "").strip()
    routing_payload = dict(payload)
    print("WA DEBUG --- webhook hit ---")
    print("WA DEBUG payload_keys=", sorted(list(payload.keys())))
    print("WA DEBUG raw_payload=", {k: payload.get(k) for k in ('direction','from','sender','to','recipient','whatsapp_chat_id','whatsapp_message_id','external_account_id','provider')})
    print("WA DEBUG sender=", _pick_sender(payload))
    print("WA DEBUG recipient=", _pick_recipient(payload))
    print("WA DEBUG direction=", str(payload.get('direction') or 'inbound').strip().lower())
    print("WA DEBUG provider=", str(payload.get('provider') or request.headers.get('X-Provider') or ''))
    print("WA DEBUG external_account_id=", str(payload.get('external_account_id') or payload.get('whatsapp_client_id') or request.headers.get('X-External-Account-Id') or ''))
    print("WA DEBUG secret_present=", bool(request.headers.get('X-Webhook-Secret') or request.query_params.get('secret') or request.query_params.get('webhook_secret') or request.headers.get('X-Webhook-Token')))
    direction = str(payload.get("direction") or "inbound").strip().lower()
    tenant_id = payload.get("tenant_id")
    routing_strategy = None
    routing_matched_value = None
    tenant = None
    if direction == "outbound" and tenant_id is not None and str(tenant_id).strip() != "":
        try:
            tenant_lookup_id = int(tenant_id)
        except (TypeError, ValueError):
            tenant_lookup_id = None
        if tenant_lookup_id is not None:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_lookup_id).first()
            routing_strategy = "explicit_tenant_id"
            routing_matched_value = str(tenant_id)
    else:
        inbound_candidates = []
        seen_candidates: set[str] = set()
        for value in [payload.get("sender_normalized"), payload.get("sender"), payload.get("from"), payload.get("sender_raw"), payload.get("whatsapp_chat_id")]:
            for candidate in phone_match_candidates(value if isinstance(value, str) else None):
                if candidate not in seen_candidates:
                    seen_candidates.add(candidate)
                    inbound_candidates.append(candidate)
        print("WA DEBUG inbound candidates=", inbound_candidates)
        routing_result = resolve_tenant_for_inbound_channel(db, routing_payload, dict(request.headers), dict(request.query_params))
        tenant = routing_result.tenant
        routing_strategy = routing_result.strategy
        routing_matched_value = getattr(routing_result, 'matched_value', None)
        print("WA DEBUG inbound routing_strategy=", routing_strategy)
        print("WA DEBUG inbound tenant_id=", getattr(tenant, 'id', None))
    print("WA DEBUG routing_strategy=", routing_strategy, "matched_value=", routing_matched_value, "tenant_id=", getattr(tenant, 'id', None))
    logger.info(
        "WhatsApp webhook received sender=%s recipient=%s provider=%s external_account_id=%s routing_strategy=%s secret_present=%s",
        sender,
        recipient,
        provider,
        external_account_id or None,
        routing_strategy,
        _secret_present(request),
    )

    if tenant is None:
        logger.warning("WhatsApp webhook tenant lookup failed strategy=%s sender=%s payload_keys=%s", routing_strategy, sender, sorted(list(payload.keys()))[:25])
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"ok": False, "error": "Tenant not found", "routing_strategy": routing_strategy})

    provider_message_id = str(payload.get("whatsapp_message_id") or payload.get("provider_message_id") or "").strip() or None
    if provider_message_id:
        if db.query(Communication).filter(Communication.provider_message_id == provider_message_id).first() is not None:
            print("WA DEBUG final_saved_tenant=", getattr(tenant, 'id', None), "provider_message_id=", payload.get('whatsapp_message_id'))
            return WhatsAppWebhookResponse(ok=True, routing_strategy=routing_strategy, tenant_id=tenant.id, message="duplicate skipped")
    else:
        msg_text = _first_text(payload)
        ts = _pick_timestamp(payload)
        if db.query(Communication).filter(
            Communication.tenant_id == tenant.id,
            Communication.channel == "whatsapp",
            Communication.message == msg_text,
            Communication.created_at == ts,
        ).first() is not None:
            print("WA DEBUG final_saved_tenant=", getattr(tenant, 'id', None), "provider_message_id=", payload.get('whatsapp_message_id'))
            return WhatsAppWebhookResponse(ok=True, routing_strategy=routing_strategy, tenant_id=tenant.id, message="duplicate skipped")

    db.add(
        Communication(
            tenant_id=tenant.id,
            channel="whatsapp",
            direction=str(payload.get("direction") or "inbound").strip().lower(),
            provider_message_id=provider_message_id,
            subject=payload.get("subject"),
            message=_first_text(payload),
            created_at=_pick_timestamp(payload),
        )
    )
    db.commit()
    print("WA DEBUG final_saved_tenant=", getattr(tenant, 'id', None), "provider_message_id=", payload.get('whatsapp_message_id'))
    return WhatsAppWebhookResponse(ok=True, routing_strategy=routing_strategy, tenant_id=tenant.id)

