from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User
from app.schemas.communication import CommunicationCreate, CommunicationRead
from app.schemas.tenant_channel_endpoint import TenantChannelEndpointRead
from app.services.thread_timeline_service import MixedTimelineRead, build_tenant_thread_timeline
from app.services.whatsapp_client import send_whatsapp_message

router = APIRouter(prefix="/communications", tags=["communications"])


class WhatsAppOutboundResolutionRead(BaseModel):
    found: bool
    tenant_id: int | None = None
    communication_id: int | None = None
    provider_message_id: str | None = None
    whatsapp_chat_id: str | None = None
    external_account_id: str | None = None
    resolution_strategy: str | None = None


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


@router.get("/whatsapp/outbound-resolution", response_model=WhatsAppOutboundResolutionRead)
def resolve_whatsapp_outbound_communication(
    provider_message_id: str | None = None,
    whatsapp_chat_id: str | None = None,
    external_account_id: str | None = None,
    db: Session = Depends(get_db),
) -> WhatsAppOutboundResolutionRead:
    provider_message_id = provider_message_id.strip() if isinstance(provider_message_id, str) else None
    whatsapp_chat_id = whatsapp_chat_id.strip() if isinstance(whatsapp_chat_id, str) else None
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
                external_account_id=communication.external_account_id,
                resolution_strategy="provider_message_id",
            )

    if whatsapp_chat_id and external_account_id:
        communication = (
            db.query(Communication)
            .filter(
                Communication.channel == "whatsapp",
                Communication.direction == "outbound",
                Communication.whatsapp_chat_id == whatsapp_chat_id,
                Communication.external_account_id == external_account_id,
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
                external_account_id=communication.external_account_id,
                resolution_strategy="chat_id_external_account_id",
            )

    return WhatsAppOutboundResolutionRead(
        found=False,
        resolution_strategy="unresolved",
        provider_message_id=provider_message_id,
        whatsapp_chat_id=whatsapp_chat_id,
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
        whatsapp_to = (tenant.phone or tenant.mobile or "").strip()
        if not whatsapp_to:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant phone is required for WhatsApp")
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
            selected_endpoint = (
                db.query(TenantChannelEndpoint)
                .filter(
                    TenantChannelEndpoint.tenant_id == tenant.id,
                    TenantChannelEndpoint.external_account_id == payload.external_account_id.strip(),
                )
                .first()
            )
        if selected_endpoint is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a WhatsApp account to send from")
        if not selected_endpoint.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected WhatsApp account is inactive")
        if (selected_endpoint.channel_type or "").strip().lower() != "whatsapp":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected endpoint is not WhatsApp-capable")
        endpoint_provider = (selected_endpoint.provider or "").strip().lower()
        if not endpoint_provider.startswith("whatsapp"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected endpoint is not WhatsApp-capable")
        selected_external_account_id = (selected_endpoint.external_account_id or "").strip()
        if not selected_external_account_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected WhatsApp account is missing an external account id")
        print("WA DEBUG backend send outbound tenant_id=", tenant.id, "external_account_id=", selected_external_account_id, "whatsapp_endpoint_id=", selected_endpoint.id)
        whatsapp_result = await send_whatsapp_message(
            {
                "to": whatsapp_to,
                "message": message,
                "tenant_id": tenant.id,
                "whatsapp_endpoint_id": selected_endpoint.id,
                "external_account_id": selected_external_account_id,
            }
        )
        print("WA DEBUG backend send response tenant_id=", tenant.id, "external_account_id=", selected_external_account_id, "message_id=", (whatsapp_result.get("whatsapp_message_id") if isinstance(whatsapp_result, dict) else None))
    else:
        whatsapp_result = None

    communication = Communication(
        tenant_id=tenant.id,
        channel=channel,
        direction="outbound",
        provider=(selected_endpoint.provider if selected_endpoint is not None else None),
        external_account_id=(selected_endpoint.external_account_id if selected_endpoint is not None else None),
        external_phone_id=(selected_endpoint.external_phone_id if selected_endpoint is not None else None),
        external_chat_namespace=(selected_endpoint.external_chat_namespace if selected_endpoint is not None else None),
        whatsapp_chat_id=(whatsapp_result.get("whatsapp_chat_id") if isinstance(whatsapp_result, dict) else None) if channel == "whatsapp" else None,
        provider_message_id=(
            (whatsapp_result.get("whatsapp_message_id") if isinstance(whatsapp_result, dict) else None)
            or (whatsapp_result.get("provider_message_id") if isinstance(whatsapp_result, dict) else None)
        ) if channel == "whatsapp" else None,
        subject=payload.subject.strip() if payload.subject and payload.subject.strip() else None,
        message=message,
        created_at=datetime.now(timezone.utc),
    )
    db.add(communication)
    db.commit()
    db.refresh(communication)
    return communication
