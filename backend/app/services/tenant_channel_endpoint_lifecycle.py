from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint

WHATSAPP_CHANNEL_TYPE = "whatsapp"
WHATSAPP_PROVIDER = "whatsapp-service"


def get_default_whatsapp_external_account_id() -> str:
    value = os.getenv("WHATSAPP_CLIENT_ID", "").strip()
    return value or "edi-crm-whatsapp"


def ensure_whatsapp_endpoint_for_tenant(
    db: Session,
    tenant: Tenant,
    external_account_id: str | None = None,
) -> TenantChannelEndpoint:
    if tenant.id is None:
        raise ValueError("tenant must be persisted before creating a WhatsApp endpoint")

    resolved_external_account_id = (external_account_id or get_default_whatsapp_external_account_id()).strip()
    endpoint = (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.channel_type == WHATSAPP_CHANNEL_TYPE,
            TenantChannelEndpoint.tenant_id == tenant.id,
            TenantChannelEndpoint.provider == WHATSAPP_PROVIDER,
            TenantChannelEndpoint.external_account_id == resolved_external_account_id,
        )
        .first()
    )
    if endpoint is None:
        endpoint = TenantChannelEndpoint(
            tenant_id=tenant.id,
            channel_type=WHATSAPP_CHANNEL_TYPE,
            provider=WHATSAPP_PROVIDER,
            external_account_id=resolved_external_account_id,
            is_active=True,
        )
        db.add(endpoint)
    else:
        endpoint.tenant_id = tenant.id
        endpoint.channel_type = WHATSAPP_CHANNEL_TYPE
        endpoint.provider = WHATSAPP_PROVIDER
        endpoint.external_account_id = resolved_external_account_id
        endpoint.is_active = True
    return endpoint


def delete_tenant_channel_endpoints(db: Session, tenant_id: int) -> int:
    return (
        db.query(TenantChannelEndpoint)
        .filter(TenantChannelEndpoint.tenant_id == tenant_id)
        .delete(synchronize_session=False)
    )
