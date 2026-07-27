from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.admin_settings import AdminSettings
from app.models.ai_reply_template import AiReplyTemplate
from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.user import User
from app.schemas.communication import CommunicationCreate, CommunicationRead
from app.schemas.tenant_channel_endpoint import TenantChannelEndpointRead
from app.services import ai_reply_service
from app.services.email_outbound_persistence import persist_gmail_outbound_message
from app.services.gemini_client import GeminiClientError
from app.services.gmail_client import GMAIL_SCOPES, build_gmail_credentials, list_thread_drafts, send_gmail_forward, send_gmail_reply
from app.services.tenant_channel_resolver import (
    _lookup_whatsapp_endpoint_by_exact_chat_identity,
    _lookup_whatsapp_endpoint_by_normalized_chat_identity,
)
from app.services.tenant_phone_aliases import get_tenant_primary_phone_raw
from app.services.thread_timeline_service import MixedTimelineRead, build_tenant_thread_timeline
from app.services.whatsapp_outbound_persistence import persist_whatsapp_outbound_communication
from app.services.whatsapp_client import WhatsAppBridgeError, send_whatsapp_message
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


class EmailForwardRequest(BaseModel):
    email_thread_id: int
    subject: str | None = None
    body: str


class GmailDraftRead(BaseModel):
    draft_id: str | None = None
    subject: str
    body_text: str


class AiDraftGenerateRequest(BaseModel):
    channel: str
    template_id: int | None = None
    rough_draft: str | None = None


class AiDraftGenerateResponse(BaseModel):
    generated_text: str
    template_id: int


class AiDraftPreviewResponse(BaseModel):
    payload: str
    char_count: int
    approx_token_count: int
    template_id: int


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


def _to_endpoint_read(endpoint: TenantChannelEndpoint) -> TenantChannelEndpointRead:
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
    )


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
    return [_to_endpoint_read(endpoint) for endpoint in endpoints]


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

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

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
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tenant has multiple chats linked on this account; select a specific WhatsApp chat to send from",
                )
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
                from_email=account.email_address,
                in_reply_to_message_id=in_reply_to_message_id,
                references=references,
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
            subject=payload.subject.strip() if payload.subject else (conversation.subject or ""),
            message=message,
            gmail_result=gmail_result,
        )

    if channel == "whatsapp":
        # Immediately persist the outbound message to ensure UI visibility
        # Use the selected endpoint's chat namespace if available for better identity matching
        communication_result = persist_whatsapp_outbound_communication(
            db,
            tenant_id=tenant.id,
            provider=(selected_endpoint.provider if selected_endpoint is not None else None),
            external_account_id=(selected_endpoint.external_account_id if selected_endpoint is not None else None),
            external_phone_id=(selected_endpoint.external_phone_id if selected_endpoint is not None else None),
            external_chat_namespace=(selected_endpoint.external_chat_namespace if selected_endpoint is not None else None),
            whatsapp_chat_id=(whatsapp_result.get("whatsapp_chat_id") if isinstance(whatsapp_result, dict) else None),
            whatsapp_identity_key=(whatsapp_result.get("whatsapp_identity_key") if isinstance(whatsapp_result, dict) else None),
            whatsapp_normalized_phone=(whatsapp_result.get("whatsapp_normalized_phone") if isinstance(whatsapp_result, dict) else None),
            provider_message_id=(
                (whatsapp_result.get("whatsapp_message_id") if isinstance(whatsapp_result, dict) else None)
                or (whatsapp_result.get("provider_message_id") if isinstance(whatsapp_result, dict) else None)
            ),
            subject=payload.subject.strip() if payload.subject and payload.subject.strip() else None,
            message=message,
            created_at=datetime.now(timezone.utc),
        )
        communication = communication_result.communication
        logger.info(
            "WhatsApp outbound communication persisted source=backend_send persistence_state=%s match_strategy=%s tenant_id=%s communication_id=%s provider_message_id=%s external_chat_namespace=%s",
            communication_result.persistence_state,
            communication_result.match_strategy,
            communication.tenant_id,
            communication.id,
            communication.provider_message_id,
            communication.external_chat_namespace,
        )
        return communication


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

    try:
        gmail_result = send_gmail_forward(
            credentials,
            thread_id=conversation.provider_thread_id,
            to_email=forward_to_email,
            subject=subject,
            body_text=full_body,
            from_email=account.email_address,
            in_reply_to_message_id=in_reply_to_message_id,
            references=references,
        )
    except Exception as exc:
        logger.exception("Failed to forward Gmail thread")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to forward email: {str(exc)}") from exc

    provider_message_id = gmail_result.get("id")
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider=PROVIDER_GMAIL,
            provider_message_id=provider_message_id or "",
            direction="outbound",
            sender_email=account.email_address,
            recipient_email=forward_to_email,
            subject=subject,
            body=body,
            sent_at=datetime.now(timezone.utc),
            raw_payload={"gmail": gmail_result},
        )
    )
    db.commit()

    communication = Communication(
        tenant_id=tenant.id,
        channel="email",
        direction="outbound",
        provider=PROVIDER_GMAIL,
        external_account_id=account.email_address,
        subject=subject,
        message=body,
        created_at=datetime.now(timezone.utc),
    )
    db.add(communication)
    db.commit()
    db.refresh(communication)
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

    try:
        generated_text = ai_reply_service.build_prompt_and_generate(
            db,
            tenant=tenant,
            template=template,
            channel=channel,
            rough_draft=payload.rough_draft,
        )
    except GeminiClientError as exc:
        logger.exception("AI draft generation failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return AiDraftGenerateResponse(generated_text=generated_text, template_id=template.id)


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

    prompt = ai_reply_service.assemble_prompt(
        db,
        tenant=tenant,
        template=template,
        channel=channel,
        rough_draft=payload.rough_draft,
    )

    return AiDraftPreviewResponse(
        payload=prompt,
        char_count=len(prompt),
        approx_token_count=len(prompt) // 4,
        template_id=template.id,
    )
