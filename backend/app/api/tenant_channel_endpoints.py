import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user, get_db
from app.core.security import generate_secure_token
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User
from app.schemas.tenant_channel_endpoint import (
    TenantChannelEndpointCreate,
    TenantChannelEndpointRead,
    TenantChannelEndpointUpdate,
)

router = APIRouter(prefix="/admin/tenant-channel-endpoints", tags=["tenant-channel-endpoints"])
logger = logging.getLogger(__name__)


def _routing_strategy(endpoint: TenantChannelEndpoint) -> str:
    return "webhook_token" if endpoint.webhook_token else "whatsapp_account_registry"


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


def _to_read(endpoint: TenantChannelEndpoint) -> TenantChannelEndpointRead:
    return TenantChannelEndpointRead(
        id=endpoint.id,
        tenant_id=endpoint.tenant_id,
        channel_type=endpoint.channel_type,
        provider=endpoint.provider,
        external_account_id=endpoint.external_account_id,
        external_phone_id=endpoint.external_phone_id,
        external_chat_namespace=endpoint.external_chat_namespace,
        webhook_token=_mask(endpoint.webhook_token),
        signing_secret=_mask(endpoint.signing_secret),
        is_active=endpoint.is_active,
        routing_strategy=_routing_strategy(endpoint),
        has_webhook_token=bool(endpoint.webhook_token),
        has_signing_secret=bool(endpoint.signing_secret),
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


def _validate_tenant(db: Session, tenant_id: int) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _is_whatsapp_endpoint(channel_type: str | None, provider: str | None) -> bool:
    normalized_channel = (channel_type or "").strip().lower()
    normalized_provider = (provider or "").strip().lower()
    return normalized_channel == "whatsapp" and normalized_provider.startswith("whatsapp")


def _validate_whatsapp_endpoint_constraints(
    db: Session,
    *,
    tenant_id: int,
    channel_type: str | None,
    provider: str | None,
    external_account_id: str | None,
    is_active: bool,
    exclude_endpoint_id: int | None = None,
) -> None:
    if not _is_whatsapp_endpoint(channel_type, provider) or not external_account_id:
        return

    duplicate_query = db.query(TenantChannelEndpoint).filter(
        TenantChannelEndpoint.tenant_id == tenant_id,
        TenantChannelEndpoint.channel_type == channel_type,
        TenantChannelEndpoint.provider == provider,
        TenantChannelEndpoint.external_account_id == external_account_id,
    )
    if exclude_endpoint_id is not None:
        duplicate_query = duplicate_query.filter(TenantChannelEndpoint.id != exclude_endpoint_id)
    if duplicate_query.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A tenant can only have one endpoint per WhatsApp service account",
        )

    if not is_active:
        return

    active_endpoints_query = db.query(TenantChannelEndpoint).filter(
        TenantChannelEndpoint.tenant_id == tenant_id,
        TenantChannelEndpoint.channel_type == "whatsapp",
        TenantChannelEndpoint.is_active.is_(True),
    )
    if exclude_endpoint_id is not None:
        active_endpoints_query = active_endpoints_query.filter(TenantChannelEndpoint.id != exclude_endpoint_id)

    service_keys = {
        ((item.provider or "").strip().lower(), (item.external_account_id or "").strip())
        for item in active_endpoints_query.all()
        if (item.provider or "").strip() and (item.external_account_id or "").strip()
    }
    service_keys.add(((provider or "").strip().lower(), external_account_id))
    if len(service_keys) > 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A tenant can only link up to 2 active WhatsApp services",
        )


@router.get("", response_model=list[TenantChannelEndpointRead], dependencies=[Depends(get_current_admin_user)])
def list_endpoints(db: Session = Depends(get_db)) -> list[TenantChannelEndpointRead]:
    endpoints = db.query(TenantChannelEndpoint).order_by(TenantChannelEndpoint.created_at.desc(), TenantChannelEndpoint.id.desc()).all()
    return [_to_read(endpoint) for endpoint in endpoints]


@router.post("", response_model=TenantChannelEndpointRead, dependencies=[Depends(get_current_admin_user)])
def create_endpoint(payload: TenantChannelEndpointCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> TenantChannelEndpointRead:
    _validate_tenant(db, payload.tenant_id)
    channel_type = _normalize_text(payload.channel_type)
    provider = _normalize_text(payload.provider)
    external_account_id = _normalize_text(payload.external_account_id)
    if not channel_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="channel_type is required")
    if not provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider is required")
    if not external_account_id and not payload.webhook_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="external_account_id is required unless webhook_token-only mode is used")

    _validate_whatsapp_endpoint_constraints(
        db,
        tenant_id=payload.tenant_id,
        channel_type=channel_type,
        provider=provider,
        external_account_id=external_account_id,
        is_active=payload.is_active,
    )

    endpoint = TenantChannelEndpoint(
        tenant_id=payload.tenant_id,
        channel_type=channel_type,
        provider=provider,
        external_account_id=external_account_id,
        external_phone_id=_normalize_text(payload.external_phone_id),
        external_chat_namespace=_normalize_text(payload.external_chat_namespace),
        webhook_token=_normalize_text(payload.webhook_token) or generate_secure_token(),
        signing_secret=_normalize_text(payload.signing_secret) or generate_secure_token(),
        is_active=payload.is_active,
    )
    db.add(endpoint)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate endpoint or webhook token") from exc
    db.refresh(endpoint)
    return _to_read(endpoint)


@router.patch("/{endpoint_id}", response_model=TenantChannelEndpointRead, dependencies=[Depends(get_current_admin_user)])
def update_endpoint(endpoint_id: int, payload: TenantChannelEndpointUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> TenantChannelEndpointRead:
    endpoint = db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.id == endpoint_id).first()
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")

    identity_fields_modified = False

    if payload.tenant_id is not None:
        _validate_tenant(db, payload.tenant_id)
        endpoint.tenant_id = payload.tenant_id
        identity_fields_modified = True
    if payload.channel_type is not None:
        value = _normalize_text(payload.channel_type)
        if not value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="channel_type is required")
        endpoint.channel_type = value
        identity_fields_modified = True
    if payload.provider is not None:
        value = _normalize_text(payload.provider)
        if not value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider is required")
        endpoint.provider = value
        identity_fields_modified = True
    if payload.external_account_id is not None:
        endpoint.external_account_id = _normalize_text(payload.external_account_id)
        identity_fields_modified = True
    if payload.external_phone_id is not None:
        endpoint.external_phone_id = _normalize_text(payload.external_phone_id)
    if payload.external_chat_namespace is not None:
        endpoint.external_chat_namespace = _normalize_text(payload.external_chat_namespace)
    if payload.webhook_token is not None:
        endpoint.webhook_token = _normalize_text(payload.webhook_token) or None
    if payload.signing_secret is not None:
        endpoint.signing_secret = _normalize_text(payload.signing_secret) or None
    if payload.is_active is not None:
        endpoint.is_active = payload.is_active

    if not endpoint.external_account_id and not endpoint.webhook_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="external_account_id is required unless webhook_token-only mode is used")

    if identity_fields_modified or payload.is_active is not None:
        _validate_whatsapp_endpoint_constraints(
            db,
            tenant_id=endpoint.tenant_id,
            channel_type=endpoint.channel_type,
            provider=endpoint.provider,
            external_account_id=endpoint.external_account_id,
            is_active=endpoint.is_active,
            exclude_endpoint_id=endpoint.id,
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate endpoint or webhook token") from exc
    db.refresh(endpoint)
    return _to_read(endpoint)


@router.post("/{endpoint_id}/toggle", response_model=TenantChannelEndpointRead, dependencies=[Depends(get_current_admin_user)])
def toggle_endpoint(endpoint_id: int, db: Session = Depends(get_db)) -> TenantChannelEndpointRead:
    endpoint = db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.id == endpoint_id).first()
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    endpoint.is_active = not endpoint.is_active
    db.commit()
    db.refresh(endpoint)
    return _to_read(endpoint)


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_current_admin_user)])
def delete_endpoint(endpoint_id: int, db: Session = Depends(get_db)) -> None:
    endpoint = db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.id == endpoint_id).first()
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    if endpoint.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Disable the endpoint before deleting it")
    db.delete(endpoint)
    db.commit()

