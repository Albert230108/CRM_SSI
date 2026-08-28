import base64
from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_reply_template import AiReplyTemplate
from app.models.communication import Communication
from app.models.communication_attachment import CommunicationAttachment
from app.models.communication_reply_draft import CommunicationReplyDraft
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.user import User
from app.schemas.communication import CommunicationCreate, CommunicationRead
from app.schemas.tenant_channel_endpoint import TenantChannelEndpointRead
from app.services import action_writer_trigger_service, ai_agent_orchestrator, ai_auto_draft_service, ai_reply_service, tenant_brain_trigger_service
from app.services.attachment_service import (
    AttachmentLimitExceededError,
    AttachmentNotFoundError,
    OutboundAttachment,
    link_attachments,
    load_outbound_attachments,
    store_upload,
)
from app.services.attachment_storage import max_message_bytes
from app.services.email_outbound_persistence import is_own_mailbox_address, persist_gmail_outbound_message
from app.services.gmail_attachments import GmailAttachmentNotFoundError, fetch_gmail_attachment_bytes
from app.services.gemini_client import GeminiClientError
from app.services.gmail_client import GMAIL_SCOPES, build_gmail_credentials, build_gmail_service_for_account, list_thread_drafts, send_gmail_forward, send_gmail_reply
from app.services.ai_plan_execution_service import run_ai_plan_for_draft
from app.services.tenant_channel_resolver import (
    _lookup_whatsapp_endpoint_by_exact_chat_identity,
    _lookup_whatsapp_endpoint_by_normalized_chat_identity,
)
from app.services.tenant_phone_aliases import get_tenant_primary_phone_raw
from app.services.thread_timeline_service import MixedTimelineRead, build_tenant_thread_timeline
from app.services.whatsapp_chat_directory import list_whatsapp_accounts
from app.services.whatsapp_outbound_persistence import persist_whatsapp_outbound_communication
from app.services.whatsapp_client import WhatsAppBridgeError, send_whatsapp_message
from app.api.whatsapp_thread_links import AUTO_FIRST_SEND_SOURCE, WhatsAppChatLinkConflict, link_whatsapp_chat_to_thread
from google.oauth2.credentials import Credentials
import os

router = APIRouter(prefix="/communications", tags=["communications"])
logger = logging.getLogger(__name__)
PROVIDER_GMAIL = "gmail"


def _build_gmail_credentials(account: GmailAccount) -> Credentials | None:
    return build_gmail_credentials(account)


class WhatsAppOutboundResolutionRead(BaseModel):
    found: bool
    tenant_id: int | None = None
    communication_id: int | None = None
    provider_message_id: str | None = None
    whatsapp_chat_id: str | None = None
    whatsapp_identity_key: str | None = None
    whatsapp_normalized_phone: str | None = None
    external_account_id: str | None = None
    resolution_strategy: str | None = None


class WhatsAppFirstMessageRequest(BaseModel):
    to: str
    message: str
    external_account_id: str
    provider: str = "whatsapp-service"
    attachment_ids: list[int] = []


class EmailForwardRequest(BaseModel):
    email_thread_id: int
    subject: str | None = None
    cc: str | None = None
    body: str
    # Newly uploaded attachments, by stored-blob id.
    attachment_ids: list[int] = []
    # Attachments from the thread being forwarded, encoded "{conversation_message_id}:{gmail_attachment_id}".
    # Explicit ids rather than an include-all flag: a long thread can carry far more than the
    # per-message cap, so the caller has to choose which ones travel.
    include_original_attachment_ids: list[str] = []


class GmailDraftRead(BaseModel):
    draft_id: str | None = None
    subject: str
    body_text: str
    body_html: str | None = None
    body_format: str = "plain"


class AiDraftGenerateRequest(BaseModel):
    channel: str
    template_id: int | None = None
    rough_draft: str | None = None


class AiDraftGenerateResponse(BaseModel):
    generated_text: str
    formatted_text: str | None = None
    template_id: int


class AiDraftPreviewResponse(BaseModel):
    payload: str
    char_count: int
    approx_token_count: int
    template_id: int


class ReplyDraftAttachmentRead(BaseModel):
    id: int
    filename: str
    size_bytes: int
    mime_type: str | None = None


class AiPlanRequest(BaseModel):
    channel: str
    email_thread_id: int | None = None
    whatsapp_endpoint_id: int | None = None
    rough_draft: str | None = None
    attachment_ids: list[int] = []


class AiPlanResponse(BaseModel):
    status: str
    draft_id: int | None = None
    generated_text: str | None = None
    formatted_text: str | None = None
    template_id: int | None = None
    run_id: int | None = None
    checker_passed: bool = False
    checker_feedback: str | None = None
    escalation_reason: str | None = None


def _resolve_tenant_conversation(db: Session, tenant: Tenant, email_thread_id: int) -> tuple[Conversation, GmailAccount]:
    conversation = (
        db.query(Conversation)
        .join(
            TenantConversationLink,
            (TenantConversationLink.conversation_id == Conversation.id)
            & (TenantConversationLink.unlinked_at.is_(None)),
        )
        .filter(Conversation.id == email_thread_id, TenantConversationLink.tenant_id == tenant.id)
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email thread not found")

    account = db.query(GmailAccount).filter(GmailAccount.id == conversation.provider_account_id).first()
    if account is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account for this thread is not found")
    if not account.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account is inactive")

    return conversation, account


def _mask_endpoint_value(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


def _to_endpoint_read(endpoint: TenantChannelEndpoint, *, is_most_recent_inbound: bool = False) -> TenantChannelEndpointRead:
    return TenantChannelEndpointRead(
        id=endpoint.id,
        tenant_id=endpoint.tenant_id,
        channel_type=endpoint.channel_type,
        provider=endpoint.provider,
        external_account_id=endpoint.external_account_id,
        external_phone_id=endpoint.external_phone_id,
        external_chat_namespace=endpoint.external_chat_namespace,
        chat_display_name=endpoint.chat_display_name,
        webhook_token=_mask_endpoint_value(endpoint.webhook_token),
        signing_secret=_mask_endpoint_value(endpoint.signing_secret),
        is_active=endpoint.is_active,
        routing_strategy="webhook_token" if endpoint.webhook_token else "whatsapp_account_registry",
        has_webhook_token=bool(endpoint.webhook_token),
        has_signing_secret=bool(endpoint.signing_secret),
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
        is_most_recent_inbound=is_most_recent_inbound,
    )


def _resolve_most_recent_inbound_whatsapp_endpoint(
    db: Session, tenant_id: int, *, external_account_id: str | None = None
) -> TenantChannelEndpoint | None:
    """The active WhatsApp endpoint that received the tenant's latest inbound message.

    Communications don't carry a direct FK to the endpoint they belong to, so this maps
    back via the same provider/account/chat-identity matching used for inbound routing
    (tenant_channel_resolver), handling @lid vs @c.us variants rather than a naive string
    match on external_chat_namespace.
    """
    query = db.query(Communication).filter(
        Communication.tenant_id == tenant_id,
        Communication.channel == "whatsapp",
        Communication.direction == "inbound",
    )
    if external_account_id:
        query = query.filter(Communication.external_account_id == external_account_id)
    inbound = query.order_by(Communication.created_at.desc(), Communication.id.desc()).first()
    if inbound is None:
        return None

    provider = (inbound.provider or "").strip()
    account_id = (inbound.external_account_id or "").strip()
    chat_identity = inbound.external_chat_namespace or inbound.whatsapp_chat_id
    if not provider or not account_id or not chat_identity:
        return None

    endpoint = _lookup_whatsapp_endpoint_by_exact_chat_identity(
        db, provider=provider, external_account_id=account_id, chat_identity=chat_identity
    )
    if endpoint is None:
        endpoint = _lookup_whatsapp_endpoint_by_normalized_chat_identity(
            db, provider=provider, external_account_id=account_id, chat_identity=chat_identity
        )
    return endpoint


@router.get("/tenants/{tenant_id}/timeline", response_model=list[CommunicationRead])
def get_tenant_timeline(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Communication]:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    return (
        db.query(Communication)
        .filter(Communication.tenant_id == tenant_id)
        .order_by(Communication.created_at.asc(), Communication.id.asc())
        .all()
    )


@router.get("/tenants/{tenant_id}/whatsapp-endpoints", response_model=list[TenantChannelEndpointRead])
def get_tenant_whatsapp_endpoints(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TenantChannelEndpointRead]:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    endpoints = (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.tenant_id == tenant_id,
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.is_active.is_(True),
        )
        .order_by(TenantChannelEndpoint.created_at.desc(), TenantChannelEndpoint.id.desc())
        .all()
    )
    most_recent_inbound_endpoint = _resolve_most_recent_inbound_whatsapp_endpoint(db, tenant_id) if len(endpoints) > 1 else None
    return [
        _to_endpoint_read(
            endpoint,
            is_most_recent_inbound=most_recent_inbound_endpoint is not None and endpoint.id == most_recent_inbound_endpoint.id,
        )
        for endpoint in endpoints
    ]


@router.get("/tenants/{tenant_id}/grouped-thread", response_model=MixedTimelineRead)
def get_tenant_grouped_thread(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MixedTimelineRead:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    return build_tenant_thread_timeline(db, tenant_id)


@router.get("/tenants/{tenant_id}/thread-version")
def get_tenant_thread_version(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str | None]:
    """Cheap marker the frontend polls to detect changes for a tenant's thread.

    Returns the latest of the WhatsApp (`communications`), email (`conversation_messages`),
    and tenant-record (e.g. Beds24-driven booking_status) timestamps for this tenant. The
    frontend re-fetches the full grouped thread only when this value changes, instead of
    polling the heavier endpoint.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    latest_communication_at = (
        db.query(Communication.created_at)
        .filter(Communication.tenant_id == tenant_id)
        .order_by(Communication.created_at.desc())
        .limit(1)
        .scalar()
    )
    latest_email_at = (
        db.query(ConversationMessage.sent_at)
        .join(Conversation, ConversationMessage.conversation_id == Conversation.id)
        .join(
            TenantConversationLink,
            (TenantConversationLink.conversation_id == Conversation.id)
            & (TenantConversationLink.unlinked_at.is_(None)),
        )
        .filter(TenantConversationLink.tenant_id == tenant_id)
        .order_by(ConversationMessage.sent_at.desc())
        .limit(1)
        .scalar()
    )

    candidates = [value for value in (latest_communication_at, latest_email_at, tenant.updated_at) if value is not None]
    latest_at = max(candidates) if candidates else None
    return {"latest_at": latest_at.isoformat() if latest_at else None}


class ThreadVersionRead(BaseModel):
    latest_at: str | None
    tenant_id: int | None = None
    tenant_name: str | None = None
    channel: str | None = None
    direction: str | None = None


@router.get("/thread-version", response_model=ThreadVersionRead)
def get_global_thread_version(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadVersionRead:
    """Cheap marker the tenant list polls to detect changes across any tenant.

    Same idea as `get_tenant_thread_version` but with no tenant filter, so the sidebar can
    re-sort/re-fetch the tenant list (e.g. to surface a new WhatsApp message, or recolor a
    tenant whose booking_status just changed via the Beds24 webhook) without the currently
    open tenant's thread being the only thing kept live.

    Also carries the tenant/channel/direction of whichever event produced `latest_at`, so the
    frontend can show a "new message" toast without a second request. When the latest event is
    a plain tenant-record update (e.g. Beds24 status change, no new message), those fields stay
    null. This only reflects the single most-recent event per poll tick, not a full event log.
    """
    latest_communication = (
        db.query(Communication).order_by(Communication.created_at.desc()).limit(1).first()
    )
    latest_email = (
        db.query(ConversationMessage, Conversation.tenant_id)
        .join(Conversation, ConversationMessage.conversation_id == Conversation.id)
        .order_by(ConversationMessage.sent_at.desc())
        .limit(1)
        .first()
    )
    latest_tenant_update_at = db.query(func.max(Tenant.updated_at)).scalar()

    candidates: list[tuple[Any, int | None, str | None, str | None]] = []
    if latest_communication is not None:
        candidates.append(
            (latest_communication.created_at, latest_communication.tenant_id, latest_communication.channel, latest_communication.direction)
        )
    if latest_email is not None:
        email_message, email_tenant_id = latest_email
        candidates.append((email_message.sent_at, email_tenant_id, "email", email_message.direction))
    if latest_tenant_update_at is not None:
        candidates.append((latest_tenant_update_at, None, None, None))

    if not candidates:
        return ThreadVersionRead(latest_at=None)

    latest_at, tenant_id, channel, direction = max(candidates, key=lambda item: item[0])

    tenant_name = None
    if tenant_id is not None:
        tenant_name = db.query(Tenant.name).filter(Tenant.id == tenant_id).scalar()

    return ThreadVersionRead(
        latest_at=latest_at.isoformat() if latest_at else None,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        channel=channel,
        direction=direction,
    )


@router.get("/whatsapp/outbound-resolution", response_model=WhatsAppOutboundResolutionRead)
def resolve_whatsapp_outbound_communication(
    provider_message_id: str | None = None,
    whatsapp_chat_id: str | None = None,
    whatsapp_identity_key: str | None = None,
    whatsapp_normalized_phone: str | None = None,
    external_account_id: str | None = None,
    db: Session = Depends(get_db),
) -> WhatsAppOutboundResolutionRead:
    provider_message_id = provider_message_id.strip() if isinstance(provider_message_id, str) else None
    whatsapp_chat_id = whatsapp_chat_id.strip() if isinstance(whatsapp_chat_id, str) else None
    whatsapp_identity_key = whatsapp_identity_key.strip() if isinstance(whatsapp_identity_key, str) else None
    external_account_id = external_account_id.strip() if isinstance(external_account_id, str) else None

    if provider_message_id:
        communication = (
            db.query(Communication)
            .filter(
                Communication.channel == "whatsapp",
                Communication.direction == "outbound",
                Communication.provider_message_id == provider_message_id,
            )
            .order_by(Communication.created_at.desc(), Communication.id.desc())
            .first()
        )
        if communication is not None:
            return WhatsAppOutboundResolutionRead(
                found=True,
                tenant_id=communication.tenant_id,
                communication_id=communication.id,
                provider_message_id=communication.provider_message_id,
                whatsapp_chat_id=communication.whatsapp_chat_id,
                whatsapp_identity_key=communication.whatsapp_identity_key,
                whatsapp_normalized_phone=communication.whatsapp_normalized_phone,
                external_account_id=communication.external_account_id,
                resolution_strategy="provider_message_id",
            )

    if external_account_id:
        for match_field, match_value in (
            ("whatsapp_identity_key", whatsapp_identity_key),
            ("whatsapp_chat_id", whatsapp_chat_id),
        ):
            if not match_value:
                continue
            communication = (
                db.query(Communication)
                .filter(
                    Communication.channel == "whatsapp",
                    Communication.direction == "outbound",
                    Communication.external_account_id == external_account_id,
                    getattr(Communication, match_field) == match_value,
                )
                .order_by(Communication.created_at.desc(), Communication.id.desc())
                .first()
            )
            if communication is not None:
                return WhatsAppOutboundResolutionRead(
                    found=True,
                    tenant_id=communication.tenant_id,
                    communication_id=communication.id,
                    provider_message_id=communication.provider_message_id,
                    whatsapp_chat_id=communication.whatsapp_chat_id,
                    whatsapp_identity_key=communication.whatsapp_identity_key,
                    external_account_id=communication.external_account_id,
                    resolution_strategy=("chat_id_external_account_id" if match_field == "whatsapp_chat_id" else f"{match_field}_external_account_id"),
                )

    # No prior outbound Communication exists for this chat yet (e.g. the very first message,
    # or one sent from another linked device before this session ever observed the chat). Fall
    # back to the manual TenantChannelEndpoint link, which is authoritative for outbound routing
    # regardless of whether any Communication has been persisted yet.
    if external_account_id:
        default_provider = "whatsapp-service"
        for chat_identity in (whatsapp_identity_key, whatsapp_chat_id):
            if not chat_identity:
                continue
            endpoint = _lookup_whatsapp_endpoint_by_exact_chat_identity(
                db,
                provider=default_provider,
                external_account_id=external_account_id,
                chat_identity=chat_identity,
            ) or _lookup_whatsapp_endpoint_by_normalized_chat_identity(
                db,
                provider=default_provider,
                external_account_id=external_account_id,
                chat_identity=chat_identity,
            )
            if endpoint is not None:
                return WhatsAppOutboundResolutionRead(
                    found=True,
                    tenant_id=endpoint.tenant_id,
                    provider_message_id=provider_message_id,
                    whatsapp_chat_id=whatsapp_chat_id,
                    whatsapp_identity_key=whatsapp_identity_key,
                    whatsapp_normalized_phone=whatsapp_normalized_phone,
                    external_account_id=external_account_id,
                    resolution_strategy="manual_channel_endpoint",
                )

    return WhatsAppOutboundResolutionRead(
        found=False,
        resolution_strategy="unresolved",
        provider_message_id=provider_message_id,
        whatsapp_chat_id=whatsapp_chat_id,
        whatsapp_identity_key=whatsapp_identity_key,
        external_account_id=external_account_id,
    )


def _run_ai_plan_background(
    db: Session,
    draft_id: int,
    tenant_id: int,
    channel: str,
    rough_draft: str | None,
    attachment_ids: list[int],
    user_id: int | None,
) -> None:
    run_ai_plan_for_draft(
        db,
        draft_id=draft_id,
        tenant_id=tenant_id,
        channel=channel,
        operator_note=rough_draft,
        attachment_ids=attachment_ids,
        user_id=user_id,
    )


def _persist_whatsapp_send_result(
    db: Session,
    *,
    tenant: Tenant,
    provider: str | None,
    external_account_id: str | None,
    external_phone_id: str | None,
    external_chat_namespace: str | None,
    whatsapp_result: Any,
    message: str,
    subject: str | None,
    outbound_attachments: list[OutboundAttachment],
) -> list[Communication]:
    result_dict = whatsapp_result if isinstance(whatsapp_result, dict) else {}
    # The bridge splits a send into several WhatsApp messages when attachments are present
    # (text and each file are separate messages), so persist one Communication per sent
    # message - they each have their own provider_message_id and the unique constraint on
    # (tenant_id, provider_message_id) would otherwise be the only thing keeping them apart.
    sent_messages = result_dict.get("messages")
    if not isinstance(sent_messages, list) or not sent_messages:
        sent_messages = [
            {
                "whatsapp_message_id": (
                    result_dict.get("whatsapp_message_id") or result_dict.get("provider_message_id")
                ),
                "kind": "text",
                "attachment_index": None,
            }
        ]

    persisted_communications: list[Communication] = []
    for sent in sent_messages:
        attachment_index = sent.get("attachment_index")
        if sent.get("kind") == "media" and isinstance(attachment_index, int):
            attachment = outbound_attachments[attachment_index]
            # Communication.message is NOT NULL, so a caption-less media row carries a
            # placeholder in the same house style as the inbound MEDIA_TYPE_LABELS.
            row_message = f"[File] {attachment.filename}"
            row_attachment_ids = [attachment.attachment_id]
        else:
            row_message = message
            row_attachment_ids = []

        communication_result = persist_whatsapp_outbound_communication(
            db,
            tenant_id=tenant.id,
            provider=provider,
            external_account_id=external_account_id,
            external_phone_id=external_phone_id,
            external_chat_namespace=external_chat_namespace,
            whatsapp_chat_id=result_dict.get("whatsapp_chat_id"),
            whatsapp_identity_key=result_dict.get("whatsapp_identity_key"),
            whatsapp_normalized_phone=result_dict.get("whatsapp_normalized_phone"),
            provider_message_id=sent.get("whatsapp_message_id"),
            subject=subject,
            message=row_message,
            created_at=datetime.now(timezone.utc),
        )
        communication = communication_result.communication
        if row_attachment_ids:
            link_attachments(db, attachment_ids=row_attachment_ids, communication_id=communication.id)
        persisted_communications.append(communication)
        logger.info(
            "WhatsApp outbound communication persisted source=backend_send persistence_state=%s match_strategy=%s tenant_id=%s communication_id=%s provider_message_id=%s external_chat_namespace=%s",
            communication_result.persistence_state,
            communication_result.match_strategy,
            communication.tenant_id,
            communication.id,
            communication.provider_message_id,
            communication.external_chat_namespace,
        )

    return persisted_communications


@router.post("/tenants/{tenant_id}/send", response_model=CommunicationRead, status_code=status.HTTP_201_CREATED)
async def send_tenant_communication(
    tenant_id: int,
    payload: CommunicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Communication:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    channel = payload.channel.strip().lower()
    if channel not in {"email", "whatsapp"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported channel")

    message, normalized_body_html, normalized_message_format = _normalize_message_format(channel, payload.message, payload.body_html, payload.message_format)
    message = message.strip()
    if not message and not (normalized_body_html or "").strip() and not payload.attachment_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

    try:
        outbound_attachments = load_outbound_attachments(
            db, tenant_id=tenant.id, attachment_ids=payload.attachment_ids, channel=channel
        )
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AttachmentLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    selected_endpoint = None
    if channel == "whatsapp":
        if payload.whatsapp_endpoint_id is not None:
            selected_endpoint = (
                db.query(TenantChannelEndpoint)
                .filter(
                    TenantChannelEndpoint.id == payload.whatsapp_endpoint_id,
                    TenantChannelEndpoint.tenant_id == tenant.id,
                )
                .first()
            )
        elif payload.external_account_id:
            # A tenant can have multiple active chats linked on the same account, so this
            # fallback (no specific whatsapp_endpoint_id given) is only safe when there's
            # exactly one match — otherwise we'd silently pick an arbitrary chat to send to.
            matching_endpoints = (
                db.query(TenantChannelEndpoint)
                .filter(
                    TenantChannelEndpoint.tenant_id == tenant.id,
                    TenantChannelEndpoint.external_account_id == payload.external_account_id.strip(),
                    TenantChannelEndpoint.is_active.is_(True),
                )
                .all()
            )
            if len(matching_endpoints) > 1:
                # Default to whichever of these chats most recently received an inbound
                # message from the tenant, rather than erroring out on the ambiguity.
                selected_endpoint = _resolve_most_recent_inbound_whatsapp_endpoint(
                    db, tenant.id, external_account_id=payload.external_account_id.strip()
                )
                if selected_endpoint is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Tenant has multiple chats linked on this account; select a specific WhatsApp chat to send from",
                    )
            else:
                selected_endpoint = matching_endpoints[0] if matching_endpoints else None
        if selected_endpoint is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a WhatsApp account to send from")
        if not selected_endpoint.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected WhatsApp account is inactive")
        if (selected_endpoint.channel_type or "").strip().lower() != "whatsapp":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected endpoint is not WhatsApp-capable")
        endpoint_provider = (selected_endpoint.provider or "").strip().lower()
        if not endpoint_provider.startswith("whatsapp"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected endpoint is not WhatsApp-capable")
        tenant_id_from_path = tenant.id
        selected_external_account_id = (selected_endpoint.external_account_id or "").strip()
        if not selected_external_account_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected WhatsApp account is missing an external account id")
        # Prefer the specific chat this endpoint is manually linked to, so a reply targets the
        # right chat when a tenant has multiple linked on the same account. Only a bare/unlinked
        # endpoint (no manual chat link) falls back to the tenant's generic primary phone.
        whatsapp_to = selected_endpoint.external_chat_namespace or get_tenant_primary_phone_raw(db, tenant)
        if not whatsapp_to:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant phone is required for WhatsApp")
        whatsapp_payload = {
            "to": whatsapp_to,
            "message": message,
            "tenant_id": tenant_id_from_path,
            "whatsapp_endpoint_id": selected_endpoint.id,
            "external_account_id": selected_external_account_id,
            "attachments": [
                {
                    "filename": item.filename,
                    "mime_type": item.mime_type,
                    "data_base64": base64.b64encode(item.content).decode("ascii"),
                }
                for item in outbound_attachments
            ],
        }
        print(
            "WA DEBUG backend send outbound request tenant_id=",
            tenant_id_from_path,
            "path=",
            f"/api/communications/tenants/{tenant_id_from_path}/send",
            "payload=",
            whatsapp_payload,
        )
        try:
            whatsapp_result = await send_whatsapp_message(whatsapp_payload)
        except WhatsAppBridgeError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        print("WA DEBUG backend send response tenant_id=", tenant.id, "external_account_id=", selected_external_account_id, "message_id=", (whatsapp_result.get("whatsapp_message_id") if isinstance(whatsapp_result, dict) else None))
    else:
        whatsapp_result = None

    if channel == "email":
        if payload.email_thread_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email send requires an existing thread (email_thread_id)")

        conversation = (
            db.query(Conversation)
            .join(
                TenantConversationLink,
                (TenantConversationLink.conversation_id == Conversation.id)
                & (TenantConversationLink.unlinked_at.is_(None)),
            )
            .filter(Conversation.id == payload.email_thread_id, TenantConversationLink.tenant_id == tenant.id)
            .first()
        )
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email thread not found")

        account = (
            db.query(GmailAccount)
            .filter(GmailAccount.id == conversation.provider_account_id)
            .first()
        )
        if account is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account for this thread is not found")
        if not account.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account is inactive")

        # Extract In-Reply-To and References from the latest message in the thread
        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.sent_at.desc())
            .first()
        )
        in_reply_to_message_id = None
        references = None
        if messages and messages.raw_payload and isinstance(messages.raw_payload, dict):
            headers = (messages.raw_payload.get("gmail", {}).get("payload") or {}).get("headers") or []
            for header in headers:
                if str(header.get("name", "")).lower() == "message-id":
                    in_reply_to_message_id = str(header.get("value", "")).strip()
                elif str(header.get("name", "")).lower() == "references":
                    references = str(header.get("value", "")).strip()

        # Determine recipient email (from the latest message)
        to_email = None
        if messages:
            # If the latest message was inbound (from tenant), reply to their email
            if messages.direction == "inbound" and messages.sender_email:
                to_email = messages.sender_email
            # If outbound (from us), reply to recipient
            elif messages.direction == "outbound" and messages.recipient_email:
                to_email = messages.recipient_email

        if is_own_mailbox_address(db, to_email):
            logger.warning(
                "Resolved recipient %s for conversation_id=%s is one of our own Gmail mailboxes; refusing to send",
                to_email,
                conversation.id,
            )
            to_email = None
        if not to_email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot determine recipient email for this thread")

        credentials = _build_gmail_credentials(account)
        if not credentials:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account credentials are missing or could not be decrypted")

        try:
            gmail_result = send_gmail_reply(
                credentials,
                thread_id=conversation.provider_thread_id,
                to_email=to_email,
                subject=payload.subject.strip() if payload.subject else (conversation.subject or ""),
                body_text=message,
                body_html=normalized_body_html if normalized_message_format == "email_html" else None,
                from_email=account.email_address,
                cc_email=payload.cc.strip() if payload.cc else None,
                in_reply_to_message_id=in_reply_to_message_id,
                references=references,
                attachments=outbound_attachments,
            )
        except Exception as exc:
            logger.exception("Failed to send Gmail reply")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to send email: {str(exc)}") from exc

        return persist_gmail_outbound_message(
            db,
            tenant_id=tenant.id,
            conversation=conversation,
            account=account,
            to_email=to_email,
            cc=payload.cc.strip() if payload.cc else None,
            subject=payload.subject.strip() if payload.subject else (conversation.subject or ""),
            message=message,
            gmail_result=gmail_result,
            body_html=normalized_body_html if normalized_message_format == "email_html" else None,
            attachment_ids=payload.attachment_ids,
        )

    if channel == "whatsapp":
        # Immediately persist the outbound message to ensure UI visibility
        # Use the selected endpoint's chat namespace if available for better identity matching
        persisted_communications = _persist_whatsapp_send_result(
            db,
            tenant=tenant,
            provider=(selected_endpoint.provider if selected_endpoint is not None else None),
            external_account_id=(selected_endpoint.external_account_id if selected_endpoint is not None else None),
            external_phone_id=(selected_endpoint.external_phone_id if selected_endpoint is not None else None),
            external_chat_namespace=(selected_endpoint.external_chat_namespace if selected_endpoint is not None else None),
            whatsapp_result=whatsapp_result,
            message=message,
            subject=payload.subject.strip() if payload.subject and payload.subject.strip() else None,
            outbound_attachments=outbound_attachments,
        )

        # The response model is a single CommunicationRead; the frontend reloads the whole
        # thread right after a send, so returning the first row is sufficient.
        return persisted_communications[0]


@router.post("/tenants/{tenant_id}/send-first-message", response_model=CommunicationRead, status_code=status.HTTP_201_CREATED)
async def send_first_whatsapp_message(
    tenant_id: int,
    payload: WhatsAppFirstMessageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Communication:
    """Sends the first WhatsApp message to a given phone number for a tenant, whether or not
    the tenant already has other active WhatsApp chats linked (e.g. a different family
    member's number).

    Unlike /send, there is no existing TenantChannelEndpoint to route through for this
    specific number - the caller supplies the destination phone and sending account
    directly. On success, the resulting chat is auto-linked as another active WhatsApp
    endpoint for the tenant (source=auto_first_send) so subsequent replies to it use the
    normal linked-chat flow with no separate manual "Link chat" step. If the chat id
    whatsapp-service returns turns out to already be linked to a *different* tenant, the
    message has already been sent by that point - we do not fail the request, we just skip
    auto-linking and log the conflict; the operator can resolve it via the existing manual
    "Link chat" flow afterward.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    to = payload.to.strip()
    external_account_id = payload.external_account_id.strip()
    message = payload.message.strip()
    if not to:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone number is required")
    if not external_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a WhatsApp account to send from")
    if not message and not payload.attachment_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

    # A tenant may already have one or more other active WhatsApp chats linked (e.g. different
    # family members texting from different numbers) - that's not a conflict for *this* number.
    # The real conflict case - this exact chat_id already linked to a *different* tenant - is
    # handled below, after the send, via link_whatsapp_chat_to_thread's own guard.

    connected_account_ids = {
        str(account.get("external_account_id") or "").strip() for account in list_whatsapp_accounts()
    }
    if external_account_id not in connected_account_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected WhatsApp account is not connected")

    try:
        outbound_attachments = load_outbound_attachments(
            db, tenant_id=tenant.id, attachment_ids=payload.attachment_ids, channel="whatsapp"
        )
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AttachmentLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    whatsapp_payload = {
        "to": to,
        "message": message,
        "tenant_id": tenant.id,
        "whatsapp_endpoint_id": None,
        "external_account_id": external_account_id,
        "require_registered_recipient": True,
        "attachments": [
            {
                "filename": item.filename,
                "mime_type": item.mime_type,
                "data_base64": base64.b64encode(item.content).decode("ascii"),
            }
            for item in outbound_attachments
        ],
    }
    try:
        whatsapp_result = await send_whatsapp_message(whatsapp_payload)
    except WhatsAppBridgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    persisted_communications = _persist_whatsapp_send_result(
        db,
        tenant=tenant,
        provider=payload.provider,
        external_account_id=external_account_id,
        external_phone_id=None,
        external_chat_namespace=None,
        whatsapp_result=whatsapp_result,
        message=message,
        subject=None,
        outbound_attachments=outbound_attachments,
    )

    result_dict = whatsapp_result if isinstance(whatsapp_result, dict) else {}
    chat_id = result_dict.get("whatsapp_chat_id")
    if chat_id:
        try:
            link_whatsapp_chat_to_thread(
                db,
                thread_id=tenant.id,
                provider=payload.provider,
                external_account_id=external_account_id,
                chat_id=chat_id,
                chat_display_name=result_dict.get("whatsapp_contact_name"),
                source=AUTO_FIRST_SEND_SOURCE,
                linked_by_user_id=current_user.id,
                background_tasks=background_tasks,
                resync=False,
            )
        except WhatsAppChatLinkConflict as exc:
            logger.warning(
                "whatsapp_first_send_chat_conflict tenant_id=%s conflicting_tenant_id=%s chat_id=%s",
                tenant.id,
                exc.conflicting_tenant_id,
                chat_id,
            )
    else:
        logger.warning(
            "whatsapp_first_send_missing_chat_id tenant_id=%s external_account_id=%s",
            tenant.id,
            external_account_id,
        )

    return persisted_communications[0]


@router.post("/tenants/{tenant_id}/forward", response_model=CommunicationRead, status_code=status.HTTP_201_CREATED)
async def forward_tenant_email_thread(
    tenant_id: int,
    payload: EmailForwardRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Communication:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

    conversation, account = _resolve_tenant_conversation(db, tenant, payload.email_thread_id)

    admin_settings = db.query(AdminSettings).first()
    forward_to_email = (admin_settings.forward_to_email if admin_settings else None) or None
    if not forward_to_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Forwarding address is not configured in Admin Settings")

    # Extract In-Reply-To/References from the latest message, and quote the full thread
    # history, so the forward stays within the same Gmail thread — this lets draft
    # retrieval later filter by threadId to find the AI-authored reply for this tenant.
    thread_messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.sent_at.asc())
        .all()
    )
    latest_message = thread_messages[-1] if thread_messages else None
    in_reply_to_message_id = None
    references = None
    if latest_message and latest_message.raw_payload and isinstance(latest_message.raw_payload, dict):
        headers = (latest_message.raw_payload.get("gmail", {}).get("payload") or {}).get("headers") or []
        for header in headers:
            if str(header.get("name", "")).lower() == "message-id":
                in_reply_to_message_id = str(header.get("value", "")).strip()
            elif str(header.get("name", "")).lower() == "references":
                references = str(header.get("value", "")).strip()

    quote_lines = ["", "---------- Forwarded message ----------"]
    for thread_message in thread_messages:
        sender = thread_message.sender_email or (account.email_address if thread_message.direction == "outbound" else "Unknown")
        quote_lines.append(f"\nOn {thread_message.sent_at.isoformat()}, {sender} wrote:")
        quote_lines.append(thread_message.body or "")
    full_body = body + "\n".join(quote_lines)

    subject = payload.subject.strip() if payload.subject else (conversation.subject or "")

    credentials = _build_gmail_credentials(account)
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account credentials are missing or could not be decrypted")

    # Newly uploaded attachments first, then whichever of the thread's own attachments the
    # caller selected. Both share the one per-message cap.
    try:
        forward_attachments = load_outbound_attachments(
            db, tenant_id=tenant.id, attachment_ids=payload.attachment_ids, channel="email"
        )
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AttachmentLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    thread_messages_by_id = {thread_message.id: thread_message for thread_message in thread_messages}
    budget = max_message_bytes("email")
    used_bytes = sum(len(item.content) for item in forward_attachments)
    omitted_count = 0
    stored_original_ids: list[int] = []

    for encoded in payload.include_original_attachment_ids:
        message_id_text, _, gmail_attachment_id = str(encoded).partition(":")
        try:
            source_message = thread_messages_by_id[int(message_id_text)]
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Attachment reference '{encoded}' is not part of this thread",
            ) from exc

        try:
            data, filename, mime_type = fetch_gmail_attachment_bytes(
                db,
                build_service_for_account=build_gmail_service_for_account,
                message=source_message,
                attachment_id=gmail_attachment_id,
            )
        except GmailAttachmentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        # Overflow is surfaced in the body rather than silently dropping files.
        if used_bytes + len(data) > budget:
            omitted_count += 1
            continue
        used_bytes += len(data)

        record = store_upload(
            db,
            tenant_id=tenant.id,
            filename=filename,
            mime_type=mime_type,
            data=data,
            user_id=current_user.id,
            origin="gmail",
        )
        stored_original_ids.append(record.id)
        forward_attachments.append(
            OutboundAttachment(
                attachment_id=record.id, filename=filename, mime_type=mime_type, content=data
            )
        )

    if omitted_count:
        full_body = (
            f"{full_body}\n\n({omitted_count} attachment(s) omitted: the message would exceed "
            f"the {budget} byte size limit.)"
        )

    try:
        gmail_result = send_gmail_forward(
            credentials,
            thread_id=conversation.provider_thread_id,
            to_email=forward_to_email,
            cc_email=payload.cc.strip() if payload.cc else None,
            subject=subject,
            body_text=full_body,
            from_email=account.email_address,
            in_reply_to_message_id=in_reply_to_message_id,
            references=references,
            attachments=forward_attachments,
        )
    except Exception as exc:
        logger.exception("Failed to forward Gmail thread")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to forward email: {str(exc)}") from exc

    provider_message_id = gmail_result.get("id")
    forward_message = ConversationMessage(
        conversation_id=conversation.id,
        provider=PROVIDER_GMAIL,
        provider_message_id=provider_message_id or "",
        direction="outbound",
        sender_email=account.email_address,
        recipient_email=forward_to_email,
        subject=subject,
        cc=payload.cc.strip() if payload.cc else None,
        body=body,
        sent_at=datetime.now(timezone.utc),
        raw_payload={"gmail": gmail_result, "cc": payload.cc.strip() if payload.cc else None},
    )
    db.add(forward_message)
    db.commit()

    communication = Communication(
        tenant_id=tenant.id,
        channel="email",
        direction="outbound",
        provider=PROVIDER_GMAIL,
        external_account_id=account.email_address,
        subject=subject,
        cc=payload.cc.strip() if payload.cc else None,
        message=body,
        created_at=datetime.now(timezone.utc),
    )
    db.add(communication)
    tenant_brain_trigger_service.register_message_trigger(
        db, tenant_id=tenant.id, channel="email", direction="outbound", email_thread_id=conversation.id
    )
    action_writer_trigger_service.register_message_trigger(
        db, tenant_id=tenant.id, channel="email", direction="outbound", email_thread_id=conversation.id
    )
    db.commit()
    db.refresh(communication)

    sent_attachment_ids = list(payload.attachment_ids) + stored_original_ids
    if sent_attachment_ids:
        link_attachments(db, attachment_ids=sent_attachment_ids, conversation_message_id=forward_message.id)
        link_attachments(db, attachment_ids=sent_attachment_ids, communication_id=communication.id)

    return communication


@router.get("/tenants/{tenant_id}/threads/{conversation_id}/draft", response_model=list[GmailDraftRead])
async def get_tenant_thread_draft(
    tenant_id: int,
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    conversation, account = _resolve_tenant_conversation(db, tenant, conversation_id)

    credentials = _build_gmail_credentials(account)
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account credentials are missing or could not be decrypted")

    try:
        return list_thread_drafts(credentials, conversation.provider_thread_id)
    except Exception as exc:
        logger.exception("Failed to list Gmail drafts for thread")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to retrieve drafts: {str(exc)}") from exc


def _resolve_ai_draft_tenant_template(
    db: Session, tenant_id: int, channel: str, template_id: int | None
) -> tuple[Tenant, str, AiReplyTemplate]:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    normalized_channel = channel.strip().lower()
    if normalized_channel not in {"email", "whatsapp"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported channel")

    resolved_template_id = template_id
    if resolved_template_id is None:
        ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
        if ai_settings is not None:
            resolved_template_id = (
                ai_settings.default_email_template_id if normalized_channel == "email" else ai_settings.default_whatsapp_template_id
            )
    if resolved_template_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No AI template selected and no default template is configured for this tenant and channel",
        )

    template = db.query(AiReplyTemplate).filter(AiReplyTemplate.id == resolved_template_id).first()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    return tenant, normalized_channel, template


def _drafter_context(db: Session, tenant_id: int) -> tuple[dict[str, str], str | None]:
    """The drafter's prompt scaffolding for this tenant, honouring any pinned drafter profile.

    Both the generate and the preview endpoint go through this, so the preview cannot drift from
    what is actually sent.
    """
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    return ai_agent_orchestrator.resolve_drafter_context(
        db, ai_settings.drafter_profile_id if ai_settings is not None else None
    )


@router.post("/tenants/{tenant_id}/ai-draft", response_model=AiDraftGenerateResponse)
def generate_tenant_ai_draft(
    tenant_id: int,
    payload: AiDraftGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiDraftGenerateResponse:
    """Stateless "Draft with AI" generation for the reply box - the caller pastes the result
    into the reply textarea for proofreading before sending; nothing is persisted here."""
    tenant, channel, template = _resolve_ai_draft_tenant_template(db, tenant_id, payload.channel, payload.template_id)
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    blocks, agent_instructions = _drafter_context(db, tenant_id)

    try:
        generated_text = ai_reply_service.build_prompt_and_generate(
            db,
            tenant=tenant,
            template=template,
            channel=channel,
            rough_draft=payload.rough_draft,
            inbound_text=ai_agent_orchestrator.latest_inbound_text(db, tenant_id, channel),
            blocks=blocks,
            agent_instructions=agent_instructions,
            drafter_profile_id=ai_settings.drafter_profile_id if ai_settings is not None else None,
        )
    except GeminiClientError as exc:
        logger.exception("AI draft generation failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    formatted_text = ai_agent_orchestrator.format_generated_draft(db, tenant, channel, generated_text)
    return AiDraftGenerateResponse(generated_text=generated_text, formatted_text=formatted_text, template_id=template.id)


@router.post("/tenants/{tenant_id}/ai-plan", response_model=AiPlanResponse)
def run_tenant_ai_planner(
    tenant_id: int,
    payload: AiPlanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiPlanResponse:
    """Run the planner -> drafter -> checker loop on demand for the reply box.

    The request now creates a draft row immediately, then completes the planner work in the
    background so the result survives the modal closing and appears in AI Drafts.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    channel = (payload.channel or "").strip().lower()
    if channel not in ("email", "whatsapp"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="channel must be email or whatsapp")

    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if ai_settings is None or (ai_settings.planner_mode or "off") == "off":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The planner is turned off for this tenant.",
        )

    if channel == "email":
        if payload.email_thread_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email_thread_id is required for email planner runs")
        # Validates the thread belongs to this tenant and the mailbox is sendable.
        _resolve_tenant_conversation(db, tenant, payload.email_thread_id)
        if payload.whatsapp_endpoint_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="whatsapp_endpoint_id is only valid for WhatsApp planner runs")
    else:
        if payload.email_thread_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email_thread_id is only valid for email planner runs")
        if payload.whatsapp_endpoint_id is not None:
            endpoint = (
                db.query(TenantChannelEndpoint)
                .filter(
                    TenantChannelEndpoint.id == payload.whatsapp_endpoint_id,
                    TenantChannelEndpoint.tenant_id == tenant.id,
                    TenantChannelEndpoint.channel_type == "whatsapp",
                    TenantChannelEndpoint.is_active.is_(True),
                )
                .first()
            )
            if endpoint is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="WhatsApp endpoint not found")

    try:
        load_outbound_attachments(db, tenant_id=tenant.id, attachment_ids=payload.attachment_ids, channel=channel)
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AttachmentLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel=channel,
        email_thread_id=(payload.email_thread_id if channel == "email" else None),
        whatsapp_endpoint_id=(payload.whatsapp_endpoint_id if channel == "whatsapp" else None),
        generated_text="",
        status="pending",
        scheduled_send_at=None,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    background_tasks.add_task(
        _run_ai_plan_background,
        db,
        draft.id,
        tenant.id,
        channel,
        payload.rough_draft,
        payload.attachment_ids,
        current_user.id,
    )

    return AiPlanResponse(status="pending", draft_id=draft.id)


@router.post("/tenants/{tenant_id}/ai-draft/preview", response_model=AiDraftPreviewResponse)
def preview_tenant_ai_draft(
    tenant_id: int,
    payload: AiDraftGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiDraftPreviewResponse:
    """Returns the exact flat prompt string that "Draft with AI" would send to Gemini, with a
    character count and an approximate (heuristic) token count, without calling Gemini. Reuses
    the same ai_reply_service.assemble_prompt() builder as generate_tenant_ai_draft so the
    preview is guaranteed to match what gets sent."""
    tenant, channel, template = _resolve_ai_draft_tenant_template(db, tenant_id, payload.channel, payload.template_id)
    blocks, agent_instructions = _drafter_context(db, tenant_id)

    prompt = ai_reply_service.assemble_prompt(
        db,
        tenant=tenant,
        template=template,
        channel=channel,
        rough_draft=payload.rough_draft,
        inbound_text=ai_agent_orchestrator.latest_inbound_text(db, tenant_id, channel),
        blocks=blocks,
        agent_instructions=agent_instructions,
    )

    return AiDraftPreviewResponse(
        payload=prompt,
        char_count=len(prompt),
        approx_token_count=len(prompt) // 4,
        template_id=template.id,
    )


class ReplyDraftRead(BaseModel):
    id: int
    tenant_id: int
    channel: str
    email_thread_id: int | None = None
    whatsapp_endpoint_id: int | None = None
    subject: str | None = None
    body: str
    body_html: str | None = None
    body_format: str = "plain"
    attachment_ids: list[int] = []
    attachments: list[ReplyDraftAttachmentRead] = []
    updated_at: datetime | None = None


class ReplyDraftUpsertRequest(BaseModel):
    channel: str
    email_thread_id: int | None = None
    whatsapp_endpoint_id: int | None = None
    subject: str | None = None
    body: str | None = None
    body_html: str | None = None
    body_format: str | None = None
    attachment_ids: list[int] = []


def _normalize_message_format(channel: str, body: str | None, body_html: str | None, body_format: str | None) -> tuple[str, str | None, str]:
    normalized_channel = (channel or "").strip().lower()
    normalized_body = body or ""
    normalized_html = (body_html or "").strip() or None
    normalized_format = (body_format or "plain").strip().lower() or "plain"

    if normalized_channel == "email":
        if normalized_format == "email_html" and normalized_html:
            return normalized_body, normalized_html, "email_html"
        return normalized_body, None, "plain"

    if normalized_channel == "whatsapp":
        if normalized_format == "whatsapp_rich" and normalized_body.strip():
            return normalized_body, normalized_html, "whatsapp_rich"
        return normalized_body, None, "plain"

    return normalized_body, None, "plain"


def _resolve_reply_draft_scope(
    db: Session,
    tenant_id: int,
    channel: str,
    email_thread_id: int | None,
    whatsapp_endpoint_id: int | None,
) -> tuple[str, int | None, int | None]:
    """Validates that the requested draft scope really belongs to this tenant.

    This is what keeps a draft from leaking between tenants: a thread id or endpoint id that
    is not linked to `tenant_id` is rejected outright rather than silently creating a row
    that a different tenant's timeline would later read back.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    normalized_channel = (channel or "").strip().lower()
    if normalized_channel not in {"email", "whatsapp"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported channel")

    if normalized_channel == "email":
        if email_thread_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email_thread_id is required for email drafts")
        # Deliberately not reusing _resolve_tenant_conversation: that also requires a live,
        # active Gmail account, and a draft must stay editable while an account is down.
        link_exists = (
            db.query(TenantConversationLink.id)
            .join(Conversation, Conversation.id == TenantConversationLink.conversation_id)
            .filter(
                TenantConversationLink.tenant_id == tenant_id,
                TenantConversationLink.conversation_id == email_thread_id,
                TenantConversationLink.unlinked_at.is_(None),
            )
            .first()
        )
        if link_exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email thread is not linked to this tenant")
        return normalized_channel, email_thread_id, None

    if whatsapp_endpoint_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="whatsapp_endpoint_id is required for WhatsApp drafts"
        )
    endpoint = (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.id == whatsapp_endpoint_id,
            TenantChannelEndpoint.tenant_id == tenant_id,
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.is_active.is_(True),
            TenantChannelEndpoint.unlinked_at.is_(None),
        )
        .first()
    )
    if endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp chat is not linked to this tenant"
        )
    return normalized_channel, None, whatsapp_endpoint_id


def _find_reply_draft(
    db: Session, tenant_id: int, channel: str, email_thread_id: int | None, whatsapp_endpoint_id: int | None
) -> CommunicationReplyDraft | None:
    query = db.query(CommunicationReplyDraft).filter(
        CommunicationReplyDraft.tenant_id == tenant_id,
        CommunicationReplyDraft.channel == channel,
    )
    if channel == "email":
        query = query.filter(CommunicationReplyDraft.email_thread_id == email_thread_id)
    else:
        query = query.filter(CommunicationReplyDraft.whatsapp_endpoint_id == whatsapp_endpoint_id)
    return query.first()


def _clean_reply_draft_attachment_ids(db: Session, tenant_id: int, attachment_ids: list[int]) -> list[int]:
    if not attachment_ids:
        return []
    records = (
        db.query(CommunicationAttachment)
        .filter(
            CommunicationAttachment.tenant_id == tenant_id,
            CommunicationAttachment.id.in_(attachment_ids),
        )
        .all()
    )
    by_id = {record.id: record for record in records}
    cleaned: list[int] = []
    seen: set[int] = set()
    for attachment_id in attachment_ids:
        if attachment_id in by_id and attachment_id not in seen:
            cleaned.append(attachment_id)
            seen.add(attachment_id)
    return cleaned


def _reply_draft_attachment_reads(
    db: Session, tenant_id: int, attachment_ids: list[int],
) -> list[ReplyDraftAttachmentRead]:
    if not attachment_ids:
        return []
    records = (
        db.query(CommunicationAttachment)
        .filter(
            CommunicationAttachment.tenant_id == tenant_id,
            CommunicationAttachment.id.in_(attachment_ids),
        )
        .all()
    )
    by_id = {record.id: record for record in records}
    attachments: list[ReplyDraftAttachmentRead] = []
    seen: set[int] = set()
    for attachment_id in attachment_ids:
        record = by_id.get(attachment_id)
        if record is None or attachment_id in seen:
            continue
        attachments.append(
            ReplyDraftAttachmentRead(
                id=record.id,
                filename=record.filename,
                size_bytes=record.size_bytes,
                mime_type=record.mime_type,
            )
        )
        seen.add(attachment_id)
    return attachments


def _to_reply_draft_read(draft: CommunicationReplyDraft, attachments: list[ReplyDraftAttachmentRead] | None = None) -> ReplyDraftRead:
    attachment_ids = list(draft.attachment_ids or [])
    if attachments is None:
        attachments = []
    return ReplyDraftRead(
        id=draft.id,
        tenant_id=draft.tenant_id,
        channel=draft.channel,
        email_thread_id=draft.email_thread_id,
        whatsapp_endpoint_id=draft.whatsapp_endpoint_id,
        subject=draft.subject,
        body=draft.body or "",
        body_html=draft.body_html,
        body_format=(draft.body_format or "plain"),
        attachment_ids=attachment_ids,
        attachments=attachments,
        updated_at=draft.updated_at,
    )


@router.get("/tenants/{tenant_id}/reply-drafts", response_model=list[ReplyDraftRead])
def list_tenant_reply_drafts(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReplyDraftRead]:
    """Every unsent reply draft for this tenant, one per thread/chat scope.

    Returned as a batch so the timeline can hydrate all of its reply boxes on tenant load
    instead of firing a request each time a thread is opened.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    drafts = (
        db.query(CommunicationReplyDraft)
        .filter(CommunicationReplyDraft.tenant_id == tenant_id)
        .order_by(CommunicationReplyDraft.updated_at.desc())
        .all()
    )
    attachment_ids = [attachment_id for draft in drafts for attachment_id in (draft.attachment_ids or [])]
    attachments_by_id = {
        attachment.id: attachment
        for attachment in (
            db.query(CommunicationAttachment)
            .filter(
                CommunicationAttachment.tenant_id == tenant_id,
                CommunicationAttachment.id.in_(attachment_ids),
            )
            .all()
        )
    }
    return [
        _to_reply_draft_read(
            draft,
            [
                ReplyDraftAttachmentRead(
                    id=attachment.id,
                    filename=attachment.filename,
                    size_bytes=attachment.size_bytes,
                    mime_type=attachment.mime_type,
                )
                for attachment_id in (draft.attachment_ids or [])
                if (attachment := attachments_by_id.get(attachment_id)) is not None
            ],
        )
        for draft in drafts
    ]


@router.put("/tenants/{tenant_id}/reply-drafts", response_model=ReplyDraftRead | None)
def upsert_tenant_reply_draft(
    tenant_id: int,
    payload: ReplyDraftUpsertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReplyDraftRead | None:
    """Saves the in-progress reply for one thread/chat, replacing any previous draft for it.

    An empty body clears the draft instead of storing a blank row, so the table stays free of
    rows for threads the user merely opened and closed.
    """
    channel, email_thread_id, whatsapp_endpoint_id = _resolve_reply_draft_scope(
        db, tenant_id, payload.channel, payload.email_thread_id, payload.whatsapp_endpoint_id
    )

    existing = _find_reply_draft(db, tenant_id, channel, email_thread_id, whatsapp_endpoint_id)
    body, body_html, body_format = _normalize_message_format(channel, payload.body, payload.body_html, payload.body_format)
    subject = payload.subject
    attachment_ids = _clean_reply_draft_attachment_ids(db, tenant_id, payload.attachment_ids)

    if not body.strip() and not (body_html or "").strip() and not (subject or "").strip() and not attachment_ids:
        if existing is not None:
            db.delete(existing)
            db.commit()
        return None

    if existing is None:
        existing = CommunicationReplyDraft(
            tenant_id=tenant_id,
            channel=channel,
            email_thread_id=email_thread_id,
            whatsapp_endpoint_id=whatsapp_endpoint_id,
        )
        db.add(existing)

    existing.subject = subject
    existing.body = body
    existing.body_html = body_html
    existing.body_format = body_format
    existing.attachment_ids = attachment_ids
    existing.updated_by_user_id = current_user.id
    db.commit()
    db.refresh(existing)
    return _to_reply_draft_read(existing, _reply_draft_attachment_reads(db, tenant_id, attachment_ids))


@router.delete("/tenants/{tenant_id}/reply-drafts", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant_reply_draft(
    tenant_id: int,
    channel: str = Query(...),
    email_thread_id: int | None = Query(None),
    whatsapp_endpoint_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Discards the draft for one scope - used by the discard button and after a successful send."""
    resolved_channel, resolved_thread_id, resolved_endpoint_id = _resolve_reply_draft_scope(
        db, tenant_id, channel, email_thread_id, whatsapp_endpoint_id
    )
    existing = _find_reply_draft(db, tenant_id, resolved_channel, resolved_thread_id, resolved_endpoint_id)
    if existing is not None:
        db.delete(existing)
        db.commit()
