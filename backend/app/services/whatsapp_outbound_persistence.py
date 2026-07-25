from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.core.whatsapp_identity import get_canonical_whatsapp_identity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WhatsAppOutboundTenantResolution:
    tenant: Tenant | None
    strategy: str
    matched_value: str | None = None
    matched_field: str | None = None
    unresolved_reason: str | None = None


@dataclass(frozen=True)
class WhatsAppOutboundPersistenceResult:
    communication: Communication
    persistence_state: str
    match_strategy: str


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def resolve_whatsapp_outbound_tenant(
    db: Session,
    *,
    tenant_id: int | str | None,
    provider: str | None,
    external_account_id: str | None,
) -> WhatsAppOutboundTenantResolution:
    normalized_provider = _normalize_text(provider)
    normalized_external_account_id = _normalize_text(external_account_id)

    if tenant_id not in (None, ""):
        try:
            tenant_lookup_id = int(str(tenant_id).strip())
        except (TypeError, ValueError):
            tenant_lookup_id = None
        if tenant_lookup_id is not None:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_lookup_id).first()
            if tenant is not None:
                logger.info("Resolved outbound WhatsApp tenant by explicit_tenant_id tenant_id=%s", tenant.id)
                return WhatsAppOutboundTenantResolution(
                    tenant=tenant,
                    strategy="explicit_tenant_id",
                    matched_value=str(tenant_lookup_id),
                    matched_field="tenant_id",
                )

    if normalized_provider and normalized_external_account_id:
        endpoint = (
            db.query(TenantChannelEndpoint)
            .filter(
                TenantChannelEndpoint.channel_type == "whatsapp",
                TenantChannelEndpoint.provider == normalized_provider,
                TenantChannelEndpoint.external_account_id == normalized_external_account_id,
                TenantChannelEndpoint.is_active.is_(True),
            )
            .first()
        )
        if endpoint is not None:
            tenant = db.query(Tenant).filter(Tenant.id == endpoint.tenant_id).first()
            if tenant is not None:
                logger.info(
                    "Resolved outbound WhatsApp tenant by account_identity tenant_id=%s provider=%s external_account_id=%s",
                    tenant.id,
                    normalized_provider,
                    normalized_external_account_id,
                )
                return WhatsAppOutboundTenantResolution(
                    tenant=tenant,
                    strategy="account_identity",
                    matched_value=normalized_external_account_id,
                    matched_field="provider+external_account_id",
                )

    logger.warning(
        "Unresolved outbound WhatsApp tenant provider=%s external_account_id=%s tenant_id=%s",
        normalized_provider or None,
        normalized_external_account_id or None,
        tenant_id,
    )
    return WhatsAppOutboundTenantResolution(
        tenant=None,
        strategy="unresolved",
        unresolved_reason="no_deterministic_match",
    )


def _find_outbound_communication(
    db: Session,
    *,
    tenant_id: int,
    provider_message_id: str | None,
    whatsapp_chat_id: str | None,
    whatsapp_identity_key: str | None,
    whatsapp_normalized_phone: str | None,
    external_account_id: str | None,
    message: str | None = None,
    created_at: datetime | None = None,
) -> tuple[Communication | None, str | None]:
    if provider_message_id:
        communication = (
            db.query(Communication)
            .filter(
                Communication.tenant_id == tenant_id,
                Communication.channel == "whatsapp",
                Communication.direction == "outbound",
                Communication.provider_message_id == provider_message_id,
            )
            .order_by(Communication.created_at.desc(), Communication.id.desc())
            .first()
        )
        if communication is not None:
            return communication, "provider_message_id"

    if external_account_id:
        # This fallback exists to "upgrade" a placeholder row created when the CRM sends a
        # message live (before WhatsApp confirms delivery with a provider_message_id) once that
        # ID arrives. It must NEVER match a row that already has its own distinct
        # provider_message_id — otherwise every subsequent outbound message in the same chat
        # whose ID lookup finds nothing (e.g. a genuinely new historical message during backfill,
        # or a live message_create capture that never got a real provider_message_id) falls
        # through to here and silently overwrites the most recent already-confirmed message's
        # text while leaving its original created_at/direction untouched, corrupting unrelated
        # history. Matching on message text alone isn't enough either — two distinct messages
        # sent moments apart with similar/identical text (e.g. from another linked device) would
        # collide on text and still overwrite each other. A genuine "same message reported twice"
        # (e.g. once via the CRM's own send API — persisted immediately with the backend's
        # wall-clock time — and once via the message_create listener observing the same physical
        # WhatsApp message a moment later) has matching text but a created_at that can differ by
        # a few seconds due to that processing gap, not an exact match. Two truly separate sends
        # ("no response in between") are realistically at least tens of seconds apart. A narrow
        # time window on top of the text match distinguishes "same message, reported twice" from
        # "two different messages that happen to say the same thing".
        DUPLICATE_CAPTURE_WINDOW = timedelta(seconds=30)
        normalized_message = _normalize_text(message)
        for match_field, match_value in (
            ("whatsapp_identity_key", whatsapp_identity_key),
            ("whatsapp_chat_id", whatsapp_chat_id),
        ):
            if not match_value:
                continue
            query = (
                db.query(Communication)
                .filter(
                    Communication.tenant_id == tenant_id,
                    Communication.channel == "whatsapp",
                    Communication.direction == "outbound",
                    Communication.external_account_id == external_account_id,
                    Communication.provider_message_id.is_(None),
                    getattr(Communication, match_field) == match_value,
                )
            )
            if normalized_message is not None:
                query = query.filter(Communication.message == normalized_message)
            candidates = query.order_by(Communication.created_at.desc(), Communication.id.desc()).limit(5).all()
            if created_at is not None:
                target = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
                communication = next(
                    (
                        candidate
                        for candidate in candidates
                        if abs(
                            (candidate.created_at if candidate.created_at.tzinfo else candidate.created_at.replace(tzinfo=timezone.utc))
                            - target
                        )
                        <= DUPLICATE_CAPTURE_WINDOW
                    ),
                    None,
                )
            else:
                communication = candidates[0] if candidates else None
            if communication is not None:
                return communication, f"{match_field}_external_account_id"

    return None, None


def _apply_outbound_metadata(
    communication: Communication,
    *,
    provider: str | None,
    external_account_id: str | None,
    external_phone_id: str | None,
    external_chat_namespace: str | None,
    whatsapp_chat_id: str | None,
    whatsapp_identity_key: str | None,
    whatsapp_normalized_phone: str | None,
    provider_message_id: str | None,
    subject: str | None,
    message: str,
    created_at: datetime | None = None,
) -> None:
    if provider is not None:
        communication.provider = provider
    if external_account_id is not None:
        communication.external_account_id = external_account_id
    if external_phone_id is not None:
        communication.external_phone_id = external_phone_id
    if external_chat_namespace is not None:
        communication.external_chat_namespace = external_chat_namespace
    if whatsapp_chat_id is not None:
        communication.whatsapp_chat_id = whatsapp_chat_id
    if whatsapp_identity_key is not None:
        communication.whatsapp_identity_key = whatsapp_identity_key
    if whatsapp_normalized_phone is not None:
        communication.whatsapp_normalized_phone = whatsapp_normalized_phone
    if provider_message_id is not None:
        communication.provider_message_id = provider_message_id
    if subject is not None:
        communication.subject = subject
    if created_at is not None:
        # Only ever passed when the match was an exact provider_message_id hit — that proves
        # it's genuinely the same WhatsApp message, so re-syncing may correct a timestamp a
        # prior (buggy) import got wrong. Never applied for the identity-key fallback match,
        # since that path matches a *different* placeholder row by design.
        communication.created_at = created_at
    communication.message = message


def persist_whatsapp_outbound_communication(
    db: Session,
    *,
    tenant_id: int,
    provider: str | None,
    external_account_id: str | None,
    external_phone_id: str | None,
    external_chat_namespace: str | None,
    whatsapp_chat_id: str | None,
    whatsapp_identity_key: str | None,
    whatsapp_normalized_phone: str | None,
    provider_message_id: str | None,
    subject: str | None,
    message: str,
    created_at: datetime,
    ai_generated: bool = False,
) -> WhatsAppOutboundPersistenceResult:
    normalized_provider = _normalize_text(provider)
    normalized_external_account_id = _normalize_text(external_account_id)
    normalized_external_phone_id = _normalize_text(external_phone_id)
    normalized_external_chat_namespace = _normalize_text(external_chat_namespace)
    normalized_whatsapp_chat_id = _normalize_text(whatsapp_chat_id)
    normalized_whatsapp_identity_key = _normalize_text(whatsapp_identity_key)
    normalized_whatsapp_normalized_phone = _normalize_text(whatsapp_normalized_phone)
    normalized_provider_message_id = _normalize_text(provider_message_id)
    normalized_subject = _normalize_text(subject)
    normalized_message = message.strip() if isinstance(message, str) else str(message).strip()
    if not normalized_message:
        raise ValueError("message cannot be empty")

    if not normalized_whatsapp_identity_key or not normalized_whatsapp_normalized_phone:
        identity = get_canonical_whatsapp_identity(
            None,
            direction="outbound",
            raw_chat_id=normalized_whatsapp_chat_id,
            recipient=normalized_whatsapp_chat_id,
            whatsapp_chat_id=normalized_whatsapp_chat_id,
            whatsapp_identity_key=normalized_whatsapp_identity_key,
            whatsapp_normalized_phone=normalized_whatsapp_normalized_phone,
        )
        normalized_whatsapp_identity_key = normalized_whatsapp_identity_key or identity.canonical_chat_id
        normalized_whatsapp_normalized_phone = normalized_whatsapp_normalized_phone or identity.normalized_phone

    communication, match_strategy = _find_outbound_communication(
        db,
        tenant_id=tenant_id,
        provider_message_id=normalized_provider_message_id,
        whatsapp_chat_id=normalized_whatsapp_chat_id,
        whatsapp_identity_key=normalized_whatsapp_identity_key,
        whatsapp_normalized_phone=normalized_whatsapp_normalized_phone,
        external_account_id=normalized_external_account_id,
        message=normalized_message,
        created_at=created_at,
    )

    persistence_state = "created"
    if communication is None:
        communication = Communication(
            tenant_id=tenant_id,
            channel="whatsapp",
            direction="outbound",
            provider=normalized_provider,
            external_account_id=normalized_external_account_id,
            external_phone_id=normalized_external_phone_id,
            external_chat_namespace=normalized_external_chat_namespace,
            whatsapp_chat_id=normalized_whatsapp_chat_id,
            whatsapp_identity_key=normalized_whatsapp_identity_key,
            whatsapp_normalized_phone=normalized_whatsapp_normalized_phone,
            provider_message_id=normalized_provider_message_id,
            subject=normalized_subject,
            message=normalized_message,
            created_at=created_at,
            ai_generated=ai_generated,
        )
        db.add(communication)
    else:
        persistence_state = "deduped"
        _apply_outbound_metadata(
            communication,
            provider=normalized_provider,
            external_account_id=normalized_external_account_id,
            external_phone_id=normalized_external_phone_id,
            external_chat_namespace=normalized_external_chat_namespace,
            whatsapp_chat_id=normalized_whatsapp_chat_id,
            whatsapp_identity_key=normalized_whatsapp_identity_key,
            whatsapp_normalized_phone=normalized_whatsapp_normalized_phone,
            provider_message_id=normalized_provider_message_id,
            subject=normalized_subject,
            message=normalized_message,
            created_at=created_at if match_strategy == "provider_message_id" else None,
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        communication, retry_match_strategy = _find_outbound_communication(
            db,
            tenant_id=tenant_id,
            provider_message_id=normalized_provider_message_id,
            whatsapp_chat_id=normalized_whatsapp_chat_id,
            whatsapp_identity_key=normalized_whatsapp_identity_key,
            whatsapp_normalized_phone=normalized_whatsapp_normalized_phone,
            external_account_id=normalized_external_account_id,
        )
        if communication is None:
            raise
        persistence_state = "deduped"
        match_strategy = retry_match_strategy or match_strategy or "provider_message_id"
        _apply_outbound_metadata(
            communication,
            provider=normalized_provider,
            external_account_id=normalized_external_account_id,
            external_phone_id=normalized_external_phone_id,
            external_chat_namespace=normalized_external_chat_namespace,
            whatsapp_chat_id=normalized_whatsapp_chat_id,
            whatsapp_identity_key=normalized_whatsapp_identity_key,
            whatsapp_normalized_phone=normalized_whatsapp_normalized_phone,
            provider_message_id=normalized_provider_message_id,
            subject=normalized_subject,
            message=normalized_message,
            created_at=created_at if match_strategy == "provider_message_id" else None,
        )
        db.commit()

    db.refresh(communication)
    logger.info(
        "WhatsApp outbound persistence persistence_state=%s match_strategy=%s tenant_id=%s communication_id=%s provider_message_id=%s whatsapp_chat_id=%s whatsapp_identity_key=%s whatsapp_normalized_phone=%s external_account_id=%s",
        persistence_state,
        match_strategy or "created",
        tenant_id,
        communication.id,
        communication.provider_message_id,
        communication.whatsapp_chat_id,
        communication.whatsapp_identity_key,
        communication.whatsapp_normalized_phone,
        communication.external_account_id,
    )
    return WhatsAppOutboundPersistenceResult(
        communication=communication,
        persistence_state=persistence_state,
        match_strategy=match_strategy or "created",
    )
