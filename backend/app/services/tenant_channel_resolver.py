import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.phone_normalization import phone_match_candidates
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutingResult:
    tenant: Tenant | None
    strategy: str
    matched_value: str | None = None


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


def resolve_tenant_for_inbound_channel(db: Session, payload: dict[str, Any], request_headers: dict[str, str], query_params: dict[str, str]) -> RoutingResult:
    provider = _first_non_empty(payload.get("provider"), query_params.get("provider"), request_headers.get("x-provider"), request_headers.get("X-Provider"))
    external_account_id = _first_non_empty(payload.get("external_account_id"), payload.get("whatsapp_client_id"), query_params.get("external_account_id"), request_headers.get("x-external-account-id"), request_headers.get("X-External-Account-Id"))
    webhook_token = _first_non_empty(payload.get("webhook_token"), request_headers.get("x-webhook-token"), request_headers.get("X-Webhook-Token"), query_params.get("webhook_token"))
    external_phone_id = _first_non_empty(payload.get("external_phone_id"), query_params.get("external_phone_id"))
    chat_namespace = _first_non_empty(payload.get("external_chat_namespace"), payload.get("whatsapp_chat_id"))

    if webhook_token:
        endpoint = db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.webhook_token == webhook_token, TenantChannelEndpoint.is_active.is_(True)).first()
        if endpoint:
            tenant = db.query(Tenant).filter(Tenant.id == endpoint.tenant_id).first()
            if tenant:
                logger.info("Resolved inbound tenant by webhook_token")
                return RoutingResult(tenant=tenant, strategy="webhook_token", matched_value=endpoint.webhook_token)

    if provider and external_account_id:
        endpoint = (
            db.query(TenantChannelEndpoint)
            .filter(
                TenantChannelEndpoint.provider == provider,
                TenantChannelEndpoint.external_account_id == external_account_id,
                TenantChannelEndpoint.is_active.is_(True),
            )
            .first()
        )
        if endpoint:
            tenant = db.query(Tenant).filter(Tenant.id == endpoint.tenant_id).first()
            if tenant:
                logger.info("Resolved inbound tenant by provider+external_account_id")
                return RoutingResult(tenant=tenant, strategy="provider_external_account_id", matched_value=external_account_id)

    legacy_sources = [
        payload.get("sender"),
        payload.get("from"),
        payload.get("sender_raw"),
        payload.get("sender_normalized"),
        chat_namespace,
        external_phone_id,
        payload.get("tenant_email"),
        payload.get("email"),
        payload.get("customer_email"),
    ]
    for email_key in ("tenant_email", "email", "customer_email"):
        value = _first_non_empty(payload.get(email_key), query_params.get(email_key))
        if value:
            tenant = db.query(Tenant).filter(Tenant.email == value).first()
            if tenant:
                logger.info("Resolved inbound tenant by legacy_email_inference")
                return RoutingResult(tenant=tenant, strategy=f"legacy_email:{email_key}", matched_value=value)

    candidates: list[str] = []
    seen: set[str] = set()
    for source in legacy_sources:
        for candidate in phone_match_candidates(source if isinstance(source, str) else None):
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

    if candidates:
        tenants = db.query(Tenant).filter(Tenant.phone.isnot(None)).all()
        tenants.extend(db.query(Tenant).filter(Tenant.mobile.isnot(None)).all())
        for tenant in tenants:
            tenant_candidates = phone_match_candidates(tenant.phone) + phone_match_candidates(tenant.mobile)
            if any(candidate in tenant_candidates for candidate in candidates):
                logger.info("Resolved inbound tenant by legacy_phone_inference")
                return RoutingResult(tenant=tenant, strategy="legacy_phone_inference", matched_value=candidates[0])

    return RoutingResult(tenant=None, strategy="unresolved")
