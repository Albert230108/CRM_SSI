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
from app.models.tenant_channel_endpoint import TenantChannelEndpoint

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
    for key in ("to", "recipient", "phone_number", "whatsapp_chat_id", "external_chat_namespace"):
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


def _normalize_phone_candidates(payload: dict[str, Any]) -> list[str]:
    inbound_candidates: list[str] = []
    seen_candidates: set[str] = set()
    for value in [payload.get("sender_normalized"), payload.get("sender"), payload.get("from"), payload.get("sender_raw"), payload.get("whatsapp_chat_id")]:
        for candidate in phone_match_candidates(value if isinstance(value, str) else None):
            if candidate not in seen_candidates:
                seen_candidates.add(candidate)
                inbound_candidates.append(candidate)
    return inbound_candidates


def _match_tenants_by_phone(db: Session, candidates: list[str]) -> list[Tenant]:
    matched: dict[int, Tenant] = {}
    for candidate in candidates:
        for tenant in db.query(Tenant).filter((Tenant.phone.isnot(None)) | (Tenant.mobile.isnot(None))).all():
            tenant_candidates = phone_match_candidates(tenant.phone) + phone_match_candidates(tenant.mobile)
            if candidate in tenant_candidates and tenant.id is not None:
                matched[tenant.id] = tenant
    return list(matched.values())


def _endpoint_from_account_identity(db: Session, provider: str, external_account_id: str) -> TenantChannelEndpoint | None:
    if not provider or not external_account_id:
        return None
    return (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.provider == provider,
            TenantChannelEndpoint.external_account_id == external_account_id,
            TenantChannelEndpoint.is_active.is_(True),
        )
        .first()
    )


@router.post("", response_model=WhatsAppWebhookResponse)
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)) -> WhatsAppWebhookResponse | JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"ok": False, "error": "Invalid webhook payload"})

    sender = _pick_sender(payload)
    recipient = _pick_recipient(payload)
    provider = str(payload.get("provider") or request.headers.get("X-Provider") or "whatsapp-service").strip()
    external_account_id = str(payload.get("external_account_id") or payload.get("whatsapp_client_id") or request.headers.get("X-External-Account-Id") or "").strip()
    external_phone_id = str(payload.get("external_phone_id") or "").strip() or None
    external_chat_namespace = str(payload.get("external_chat_namespace") or payload.get("whatsapp_chat_id") or "").strip() or None
    direction = str(payload.get("direction") or "inbound").strip().lower()
    tenant_id = payload.get("tenant_id")
    routing_strategy = None
    routing_matched_value = None
    account_endpoint = _endpoint_from_account_identity(db, provider, external_account_id)

    print("WA DEBUG --- webhook hit ---")
    print("WA DEBUG payload_keys=", sorted(list(payload.keys())))
    print("WA DEBUG raw_payload=", {k: payload.get(k) for k in ('direction','from','sender','to','recipient','whatsapp_chat_id','whatsapp_message_id','external_account_id','provider')})
    print("WA DEBUG sender=", _pick_sender(payload))
    print("WA DEBUG recipient=", _pick_recipient(payload))
    print("WA DEBUG direction=", direction)
    print("WA DEBUG provider=", provider)
    print("WA DEBUG external_account_id=", external_account_id)
    print("WA DEBUG secret_present=", _secret_present(request))
    print("WA DEBUG account_identity endpoint_id=", getattr(account_endpoint, 'id', None), "tenant_id=", getattr(account_endpoint, 'tenant_id', None))

    if direction == "outbound":
        if tenant_id is None or str(tenant_id).strip() == "":
            logger.warning("WhatsApp outbound webhook missing tenant_id provider=%s external_account_id=%s", provider, external_account_id or None)
            return WhatsAppWebhookResponse(ok=True, routing_strategy="outbound_missing_tenant", tenant_id=None, message="outbound ignored")
        try:
            tenant_lookup_id = int(tenant_id)
        except (TypeError, ValueError):
            tenant_lookup_id = None
        tenant = db.query(Tenant).filter(Tenant.id == tenant_lookup_id).first() if tenant_lookup_id is not None else None
        routing_strategy = "explicit_tenant_id"
        routing_matched_value = str(tenant_id)
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
            logger.warning("WhatsApp outbound webhook tenant lookup failed tenant_id=%s provider=%s external_account_id=%s", tenant_id, provider, external_account_id or None)
            return WhatsAppWebhookResponse(ok=True, routing_strategy=routing_strategy, tenant_id=None, message="outbound ignored")

        provider_message_id = str(payload.get("whatsapp_message_id") or payload.get("provider_message_id") or "").strip() or None
        if provider_message_id:
            duplicate = db.query(Communication).filter(Communication.tenant_id == tenant.id, Communication.provider_message_id == provider_message_id).first() is not None
        else:
            msg_text = _first_text(payload)
            ts = _pick_timestamp(payload)
            duplicate = db.query(Communication).filter(
                Communication.tenant_id == tenant.id,
                Communication.channel == "whatsapp",
                Communication.message == msg_text,
                Communication.created_at == ts,
            ).first() is not None
        if duplicate:
            print("WA DEBUG final_saved_tenant=", getattr(tenant, 'id', None), "provider_message_id=", payload.get('whatsapp_message_id'))
            return WhatsAppWebhookResponse(ok=True, routing_strategy=routing_strategy, tenant_id=tenant.id, message="duplicate skipped")

        db.add(
            Communication(
                tenant_id=tenant.id,
                channel="whatsapp",
                direction="outbound",
                provider=provider,
                external_account_id=external_account_id or None,
                external_phone_id=external_phone_id,
                external_chat_namespace=external_chat_namespace,
                whatsapp_chat_id=recipient,
                provider_message_id=provider_message_id,
                subject=payload.get("subject"),
                message=_first_text(payload),
                created_at=_pick_timestamp(payload),
            )
        )
        db.commit()
        print("WA DEBUG final_saved_tenant=", getattr(tenant, 'id', None), "provider_message_id=", payload.get('whatsapp_message_id'))
        return WhatsAppWebhookResponse(ok=True, routing_strategy=routing_strategy, tenant_id=tenant.id)

    print("WA DEBUG inbound candidates=", _normalize_phone_candidates(payload))
    webhook_token = str(payload.get("webhook_token") or request.headers.get("X-Webhook-Token") or request.query_params.get("webhook_token") or "").strip()
    target_tenants: list[Tenant] = []
    if webhook_token:
        endpoint = db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.webhook_token == webhook_token, TenantChannelEndpoint.is_active.is_(True)).first()
        if endpoint:
            tenant = db.query(Tenant).filter(Tenant.id == endpoint.tenant_id).first()
            if tenant:
                target_tenants = [tenant]
                routing_strategy = "webhook_token"
                routing_matched_value = webhook_token
    if not target_tenants:
        target_tenants = _match_tenants_by_phone(db, _normalize_phone_candidates(payload))
        if target_tenants:
            routing_strategy = "whatsapp_phone_match"
            routing_matched_value = _normalize_phone_candidates(payload)[0] if _normalize_phone_candidates(payload) else None
    print("WA DEBUG inbound matched_tenants=", [matched_tenant.id for matched_tenant in target_tenants])
    print("WA DEBUG routing_strategy=", routing_strategy, "matched_value=", routing_matched_value, "tenant_id=", target_tenants[0].id if target_tenants else None)
    logger.info(
        "WhatsApp webhook received sender=%s recipient=%s provider=%s external_account_id=%s routing_strategy=%s secret_present=%s",
        sender,
        recipient,
        provider,
        external_account_id or None,
        routing_strategy,
        _secret_present(request),
    )

    if not target_tenants:
        logger.info("WhatsApp inbound message ignored sender=%s provider=%s external_account_id=%s candidates=%s", sender, provider, external_account_id or None, _normalize_phone_candidates(payload))
        return WhatsAppWebhookResponse(ok=True, routing_strategy="ignored", tenant_id=None, message="inbound ignored")

    provider_message_id = str(payload.get("whatsapp_message_id") or payload.get("provider_message_id") or "").strip() or None
    msg_text = _first_text(payload)
    ts = _pick_timestamp(payload)
    saved_tenant_ids: list[int] = []
    for target_tenant in target_tenants:
        if provider_message_id:
            duplicate = db.query(Communication).filter(
                Communication.tenant_id == target_tenant.id,
                Communication.provider_message_id == provider_message_id,
            ).first() is not None
        else:
            duplicate = db.query(Communication).filter(
                Communication.tenant_id == target_tenant.id,
                Communication.channel == "whatsapp",
                Communication.message == msg_text,
                Communication.created_at == ts,
            ).first() is not None
        if duplicate:
            continue
        db.add(
            Communication(
                tenant_id=target_tenant.id,
                channel="whatsapp",
                direction="inbound",
                provider=provider,
                external_account_id=external_account_id or None,
                external_phone_id=external_phone_id,
                external_chat_namespace=external_chat_namespace,
                whatsapp_chat_id=recipient,
                provider_message_id=provider_message_id,
                subject=payload.get("subject"),
                message=msg_text,
                created_at=ts,
            )
        )
        saved_tenant_ids.append(target_tenant.id)
    if saved_tenant_ids:
        db.commit()
    print("WA DEBUG final_saved_tenants=", saved_tenant_ids, "provider_message_id=", payload.get('whatsapp_message_id'))
    return WhatsAppWebhookResponse(ok=True, routing_strategy=routing_strategy or "whatsapp_phone_match", tenant_id=saved_tenant_ids[0] if saved_tenant_ids else target_tenants[0].id)
