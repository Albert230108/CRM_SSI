from datetime import datetime, timezone
import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.phone_normalization import phone_match_candidates
from app.core.whatsapp_identity import get_canonical_whatsapp_identity
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services.tenant_channel_resolver import resolve_tenant_for_inbound_channel
from app.services.whatsapp_outbound_persistence import persist_whatsapp_outbound_communication, resolve_whatsapp_outbound_tenant

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhooks"])
logger = logging.getLogger(__name__)


class WhatsAppWebhookResponse(BaseModel):
    ok: bool
    routing_strategy: str | None = None
    tenant_id: int | None = None
    message: str | None = None
    unresolved_reason: str | None = None


class WhatsAppBackfillIdentityEntry(BaseModel):
    tenant_id: int
    tenant_name: str
    booking_id: str
    phone_numbers: list[str] = Field(default_factory=list)
    chat_ids: list[str] = Field(default_factory=list)
    external_phone_ids: list[str] = Field(default_factory=list)
    external_chat_namespaces: list[str] = Field(default_factory=list)
    external_account_ids: list[str] = Field(default_factory=list)


class WhatsAppBackfillIdentitiesResponse(BaseModel):
    ok: bool
    total_tenants: int
    total_active_endpoints: int
    total_identity_records: int
    entries: list[WhatsAppBackfillIdentityEntry]


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


def _configured_webhook_secret() -> str | None:
    secret = os.getenv("CRM_WEBHOOK_SECRET", "").strip()
    return secret or None


def _provided_webhook_secret(request: Request, payload: dict[str, Any]) -> str | None:
    for value in (
        request.headers.get("X-Webhook-Secret"),
        request.query_params.get("secret"),
        request.query_params.get("webhook_secret"),
        payload.get("secret"),
        payload.get("webhook_secret"),
    ):
        if value:
            return str(value).strip()
    return None


def _normalize_identity_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _append_unique(target: list[str], *values: str | None) -> None:
    seen = set(target)
    for value in values:
        normalized = _normalize_identity_value(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            target.append(normalized)


def _append_phone_candidates(target: list[str], *values: str | None) -> None:
    seen = set(target)
    for value in values:
        for candidate in phone_match_candidates(value if isinstance(value, str) else None):
            if candidate not in seen:
                seen.add(candidate)
                target.append(candidate)


def _validate_webhook_secret(request: Request, payload: dict[str, Any]) -> JSONResponse | None:
    expected_secret = _configured_webhook_secret()
    if not expected_secret:
        logger.error("WhatsApp webhook secret is not configured")
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"ok": False, "error": "Webhook secret is not configured"})

    provided_secret = _provided_webhook_secret(request, payload)
    if not provided_secret:
        logger.warning("WhatsApp webhook rejected: missing secret")
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"ok": False, "error": "Missing webhook secret"})

    if not hmac.compare_digest(provided_secret, expected_secret):
        logger.warning("WhatsApp webhook rejected: invalid secret")
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"ok": False, "error": "Invalid webhook secret"})

    return None


def _build_backfill_identity_entries(db: Session) -> tuple[list[WhatsAppBackfillIdentityEntry], int]:
    entries_by_tenant_id: dict[int, WhatsAppBackfillIdentityEntry] = {}

    for tenant in db.query(Tenant).all():
        if tenant.id is None:
            continue
        entries_by_tenant_id[tenant.id] = WhatsAppBackfillIdentityEntry(
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            booking_id=tenant.booking_id,
        )

    for tenant in db.query(Tenant).filter((Tenant.phone.isnot(None)) | (Tenant.mobile.isnot(None))).all():
        if tenant.id is None:
            continue
        entry = entries_by_tenant_id.setdefault(
            tenant.id,
            WhatsAppBackfillIdentityEntry(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                booking_id=tenant.booking_id,
            ),
        )
        _append_phone_candidates(entry.phone_numbers, tenant.phone, tenant.mobile)

    active_endpoints = (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.is_active.is_(True),
        )
        .all()
    )
    for endpoint in active_endpoints:
        if endpoint.tenant_id is None:
            continue
        tenant = db.query(Tenant).filter(Tenant.id == endpoint.tenant_id).first()
        if tenant is None:
            continue
        entry = entries_by_tenant_id.setdefault(
            tenant.id,
            WhatsAppBackfillIdentityEntry(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                booking_id=tenant.booking_id,
            ),
        )
        _append_unique(entry.external_account_ids, endpoint.external_account_id)
        _append_phone_candidates(entry.external_phone_ids, endpoint.external_phone_id)
        _append_unique(entry.external_chat_namespaces, endpoint.external_chat_namespace)
        _append_unique(entry.chat_ids, endpoint.external_chat_namespace)

    for tenant_id, whatsapp_chat_id, whatsapp_identity_key, whatsapp_normalized_phone in (
        db.query(
            Communication.tenant_id,
            Communication.whatsapp_chat_id,
            Communication.whatsapp_identity_key,
            Communication.whatsapp_normalized_phone,
        )
        .filter(
            Communication.channel == "whatsapp",
            Communication.tenant_id.isnot(None),
        )
        .distinct()
        .all()
    ):
        if tenant_id is None:
            continue
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant is None:
            continue
        entry = entries_by_tenant_id.setdefault(
            tenant.id,
            WhatsAppBackfillIdentityEntry(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                booking_id=tenant.booking_id,
            ),
        )
        _append_unique(entry.chat_ids, whatsapp_chat_id, whatsapp_identity_key)
        if not any(str(value or "").strip().lower().endswith("@g.us") for value in (whatsapp_chat_id, whatsapp_identity_key)):
            _append_phone_candidates(entry.phone_numbers, whatsapp_normalized_phone, whatsapp_identity_key)

    entries = sorted(entries_by_tenant_id.values(), key=lambda item: item.tenant_id)
    for entry in entries:
        entry.phone_numbers.sort()
        entry.chat_ids.sort()
        entry.external_phone_ids.sort()
        entry.external_chat_namespaces.sort()
        entry.external_account_ids.sort()
    return entries, len(active_endpoints)


def _normalize_phone_candidates(payload: dict[str, Any]) -> list[str]:
    inbound_candidates: list[str] = []
    seen_candidates: set[str] = set()
    for value in [payload.get("sender_normalized"), payload.get("recipient_normalized"), payload.get("whatsapp_normalized_phone"), payload.get("sender"), payload.get("from"), payload.get("sender_raw"), payload.get("recipient"), payload.get("to"), payload.get("whatsapp_chat_id"), payload.get("whatsapp_identity_key")]:
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


def _find_existing_inbound_whatsapp_communication(
    db: Session,
    *,
    tenant_id: int,
    provider_message_id: str | None,
    whatsapp_chat_id: str | None,
    whatsapp_identity_key: str | None,
    whatsapp_normalized_phone: str | None,
    external_account_id: str | None,
    message: str,
    created_at: datetime,
) -> Communication | None:
    if provider_message_id:
        return (
            db.query(Communication)
            .filter(
                Communication.tenant_id == tenant_id,
                Communication.channel == "whatsapp",
                Communication.direction == "inbound",
                Communication.provider_message_id == provider_message_id,
            )
            .first()
        )

    duplicate_query = db.query(Communication).filter(
        Communication.tenant_id == tenant_id,
        Communication.channel == "whatsapp",
        Communication.direction == "inbound",
    )
    if external_account_id:
        duplicate_query = duplicate_query.filter(Communication.external_account_id == external_account_id)
    if whatsapp_identity_key:
        duplicate_query = duplicate_query.filter(Communication.whatsapp_identity_key == whatsapp_identity_key)
    elif whatsapp_normalized_phone:
        duplicate_query = duplicate_query.filter(Communication.whatsapp_normalized_phone == whatsapp_normalized_phone)
    elif whatsapp_chat_id:
        duplicate_query = duplicate_query.filter(Communication.whatsapp_chat_id == whatsapp_chat_id)
    return duplicate_query.filter(Communication.message == message, Communication.created_at == created_at).first()


@router.post("", response_model=WhatsAppWebhookResponse)
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)) -> WhatsAppWebhookResponse | JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"ok": False, "error": "Invalid webhook payload"})

    secret_error = _validate_webhook_secret(request, payload)
    if secret_error is not None:
        return secret_error

    secret_valid = True
    sender = _pick_sender(payload)
    recipient = _pick_recipient(payload)
    provider = str(payload.get("provider") or request.headers.get("X-Provider") or "whatsapp-service").strip()
    external_account_id = str(payload.get("external_account_id") or payload.get("whatsapp_client_id") or request.headers.get("X-External-Account-Id") or "").strip()
    external_phone_id = str(payload.get("external_phone_id") or "").strip() or None
    external_chat_namespace = str(payload.get("external_chat_namespace") or payload.get("whatsapp_chat_id") or "").strip() or None
    direction = str(payload.get("direction") or "inbound").strip().lower()
    whatsapp_identity = get_canonical_whatsapp_identity(payload, direction=direction)
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
    print("WA DEBUG secret_valid=", secret_valid)
    print("WA DEBUG account_identity endpoint_id=", getattr(account_endpoint, 'id', None), "tenant_id=", getattr(account_endpoint, 'tenant_id', None))

    if direction == "outbound":
        tenant_resolution = resolve_whatsapp_outbound_tenant(
            db,
            tenant_id=tenant_id,
            provider=provider,
            external_account_id=external_account_id,
        )
        tenant = tenant_resolution.tenant
        routing_strategy = tenant_resolution.strategy
        routing_matched_value = tenant_resolution.matched_value
        print("WA DEBUG routing_strategy=", routing_strategy, "matched_value=", routing_matched_value, "tenant_id=", getattr(tenant, 'id', None))
        logger.info(
            "WhatsApp webhook received sender=%s recipient=%s provider=%s external_account_id=%s routing_strategy=%s secret_valid=%s",
            sender,
            recipient,
            provider,
            external_account_id or None,
            routing_strategy,
            secret_valid,
        )
        if tenant is None:
            logger.warning("WhatsApp outbound webhook tenant lookup failed tenant_id=%s provider=%s external_account_id=%s", tenant_id, provider, external_account_id or None)
            return WhatsAppWebhookResponse(ok=True, routing_strategy=routing_strategy, tenant_id=None, message="outbound ignored", unresolved_reason=tenant_resolution.unresolved_reason)

        provider_message_id = str(payload.get("whatsapp_message_id") or payload.get("provider_message_id") or "").strip() or None
        persistence_result = persist_whatsapp_outbound_communication(
            db,
            tenant_id=tenant.id,
            provider=provider,
            external_account_id=external_account_id or None,
            external_phone_id=external_phone_id,
            external_chat_namespace=external_chat_namespace,
            whatsapp_chat_id=whatsapp_identity.raw_chat_id,
            whatsapp_identity_key=whatsapp_identity.canonical_chat_id,
            whatsapp_normalized_phone=whatsapp_identity.normalized_phone,
            provider_message_id=provider_message_id,
            subject=payload.get("subject"),
            message=_first_text(payload),
            created_at=_pick_timestamp(payload),
        )
        print(
            "WA DEBUG final_saved_tenant=",
            getattr(tenant, 'id', None),
            "provider_message_id=",
            payload.get('whatsapp_message_id'),
            "persistence_state=",
            persistence_result.persistence_state,
            "match_strategy=",
            persistence_result.match_strategy,
        )
        message = "duplicate skipped" if persistence_result.persistence_state == "deduped" else None
        return WhatsAppWebhookResponse(ok=True, routing_strategy=routing_strategy, tenant_id=tenant.id, message=message)

    resolved = resolve_tenant_for_inbound_channel(db, payload, dict(request.headers), dict(request.query_params))
    print(
        "WA DEBUG inbound routing_strategy=",
        resolved.strategy,
        "matched_field=",
        resolved.matched_field,
        "matched_value=",
        resolved.matched_value,
        "resolved_tenant_id=",
        resolved.tenant.id if resolved.tenant else None,
        "unresolved_reason=",
        resolved.unresolved_reason,
    )
    logger.info(
        "WhatsApp inbound routing decision strategy=%s matched_field=%s matched_value=%s resolved_tenant_id=%s unresolved_reason=%s sender=%s recipient=%s provider=%s external_account_id=%s secret_valid=%s",
        resolved.strategy,
        resolved.matched_field,
        resolved.matched_value,
        resolved.tenant.id if resolved.tenant else None,
        resolved.unresolved_reason,
        sender,
        recipient,
        provider,
        external_account_id or None,
        True,
    )

    if resolved.tenant is None:
        return WhatsAppWebhookResponse(ok=True, routing_strategy="unresolved", tenant_id=None, message="inbound unresolved", unresolved_reason=resolved.unresolved_reason or resolved.strategy)

    provider_message_id = str(payload.get("whatsapp_message_id") or payload.get("provider_message_id") or "").strip() or None
    msg_text = _first_text(payload)
    ts = _pick_timestamp(payload)
    tenant = resolved.tenant
    duplicate = _find_existing_inbound_whatsapp_communication(
        db,
        tenant_id=tenant.id,
        provider_message_id=provider_message_id,
        whatsapp_chat_id=whatsapp_identity.raw_chat_id,
        whatsapp_identity_key=whatsapp_identity.canonical_chat_id,
        whatsapp_normalized_phone=whatsapp_identity.normalized_phone,
        external_account_id=external_account_id or None,
        message=msg_text,
        created_at=ts,
    )
    if duplicate:
        print("WA DEBUG final_saved_tenant=", getattr(tenant, 'id', None), "provider_message_id=", payload.get('whatsapp_message_id'))
        return WhatsAppWebhookResponse(ok=True, routing_strategy=resolved.strategy, tenant_id=tenant.id, message="duplicate skipped")

    db.add(
        Communication(
            tenant_id=tenant.id,
            channel="whatsapp",
            direction="inbound",
            provider=provider,
            external_account_id=external_account_id or None,
            external_phone_id=external_phone_id,
            external_chat_namespace=external_chat_namespace,
            whatsapp_chat_id=whatsapp_identity.raw_chat_id,
            whatsapp_identity_key=whatsapp_identity.canonical_chat_id,
            whatsapp_normalized_phone=whatsapp_identity.normalized_phone,
            provider_message_id=provider_message_id,
            subject=payload.get("subject"),
            message=msg_text,
            created_at=ts,
        )
    )
    db.commit()
    print("WA DEBUG final_saved_tenant=", getattr(tenant, 'id', None), "provider_message_id=", payload.get('whatsapp_message_id'))
    return WhatsAppWebhookResponse(ok=True, routing_strategy=resolved.strategy, tenant_id=tenant.id)

@router.get("/backfill-identities", response_model=WhatsAppBackfillIdentitiesResponse)
def whatsapp_backfill_identities(request: Request, db: Session = Depends(get_db)) -> WhatsAppBackfillIdentitiesResponse | JSONResponse:
    secret_error = _validate_webhook_secret(request, {})
    if secret_error is not None:
        return secret_error

    entries, total_active_endpoints = _build_backfill_identity_entries(db)
    return WhatsAppBackfillIdentitiesResponse(
        ok=True,
        total_tenants=len(entries),
        total_active_endpoints=total_active_endpoints,
        total_identity_records=sum(
            len(entry.phone_numbers) + len(entry.chat_ids) + len(entry.external_phone_ids) + len(entry.external_chat_namespaces)
            for entry in entries
        ),
        entries=entries,
    )
