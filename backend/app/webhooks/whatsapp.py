from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.phone_normalization import phone_match_candidates
from app.models.communication import Communication
from app.models.tenant import Tenant

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


def _pick_tenant_identifier(request: Request, payload: dict[str, Any]) -> tuple[str | None, str | None]:
    for key in ("tenant_id", "tenantId"):
        value = payload.get(key) or request.query_params.get(key)
        if value not in (None, ""):
            return str(value), key

    for key in ("tenant_slug", "tenantSlug", "subdomain", "instance_id", "instanceId", "whatsapp_instance_id", "whatsappInstanceId"):
        value = payload.get(key) or request.query_params.get(key) or request.headers.get(key.replace("_", "-").title())
        if value not in (None, ""):
            return str(value), key

    return None, None


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
    return bool(
        request.headers.get("X-Webhook-Secret")
        or request.query_params.get("secret")
        or request.query_params.get("webhook_secret")
        or request.headers.get("X-Webhook-Token")
    )


def _find_tenant(db: Session, sender: str | None, payload: dict[str, Any], request: Request) -> Tenant | None:
    tenant_id_value = payload.get("tenant_id") or payload.get("tenantId") or request.query_params.get("tenant_id") or request.query_params.get("tenantId")
    if tenant_id_value not in (None, ""):
        try:
            tenant_id = int(str(tenant_id_value))
        except (TypeError, ValueError):
            tenant_id = None
        if tenant_id is not None:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant is not None:
                logger.info("Resolved WhatsApp tenant by tenant_id=%s", tenant_id)
                return tenant
            logger.warning("WhatsApp tenant lookup by tenant_id=%s returned no tenant", tenant_id)

    for key in ("email", "customer_email", "tenant_email"):
        value = payload.get(key)
        if value:
            tenant = db.query(Tenant).filter(Tenant.email == str(value)).first()
            if tenant is not None:
                logger.info("Resolved WhatsApp tenant by %s", key)
                return tenant
            logger.warning("WhatsApp tenant lookup by %s=%s returned no tenant", key, value)

    candidate_sources = [
        sender,
        payload.get("sender_raw"),
        payload.get("sender_normalized"),
        payload.get("whatsapp_chat_id"),
        payload.get("whatsapp_author"),
        payload.get("tenant_slug"),
        payload.get("tenantSlug"),
        payload.get("subdomain"),
        payload.get("instance_id"),
        payload.get("instanceId"),
        payload.get("whatsapp_instance_id"),
        payload.get("whatsappInstanceId"),
        request.query_params.get("tenant_slug"),
        request.query_params.get("tenantSlug"),
        request.query_params.get("subdomain"),
        request.query_params.get("instance_id"),
        request.query_params.get("instanceId"),
        request.query_params.get("whatsapp_instance_id"),
        request.query_params.get("whatsappInstanceId"),
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for source in candidate_sources:
        for candidate in phone_match_candidates(source if isinstance(source, str) else None):
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

    if not candidates:
        logger.warning("WhatsApp tenant lookup had no phone candidates for sender=%s", sender)
        return None

    tenants = db.query(Tenant).filter(Tenant.phone.isnot(None)).all()
    tenants.extend(db.query(Tenant).filter(Tenant.mobile.isnot(None)).all())
    for tenant in tenants:
        tenant_candidates = phone_match_candidates(tenant.phone) + phone_match_candidates(tenant.mobile)
        if any(candidate in tenant_candidates for candidate in candidates):
            logger.info("Resolved WhatsApp tenant by phone match")
            return tenant

    logger.warning("WhatsApp tenant lookup by phone match failed sender=%s candidate_count=%s", sender, len(candidates))
    return None


@router.post("")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")

    sender = _pick_sender(payload)
    tenant_identifier, tenant_identifier_source = _pick_tenant_identifier(request, payload)
    logger.info(
        "WhatsApp webhook received sender=%s tenant_identifier_source=%s tenant_identifier_present=%s secret_present=%s",
        sender,
        tenant_identifier_source,
        bool(tenant_identifier),
        _secret_present(request),
    )

    tenant = _find_tenant(db, sender, payload, request)
    if tenant is None:
        logger.warning(
            "WhatsApp webhook tenant lookup failed sender=%s tenant_identifier_source=%s payload_keys=%s",
            sender,
            tenant_identifier_source,
            sorted(list(payload.keys()))[:25],
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

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
    return {"status": "ok"}
