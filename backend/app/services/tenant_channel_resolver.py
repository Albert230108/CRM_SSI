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


def _normalized_phone_candidates(*values: Any) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        for candidate in phone_match_candidates(value if isinstance(value, str) else None):
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
    return candidates


def _is_whatsapp_provider(provider: str | None) -> bool:
    return bool(provider and provider.strip().lower().startswith("whatsapp"))


def _match_phone_tenant(db: Session, candidates: list[str]) -> tuple[Tenant | None, str | None, dict[int, Tenant]]:
    matched_tenants: dict[int, Tenant] = {}
    matched_value: str | None = None
    for candidate in candidates:
        tenant_matches: list[Tenant] = []
        for tenant in db.query(Tenant).filter((Tenant.phone.isnot(None)) | (Tenant.mobile.isnot(None))).all():
            tenant_candidates = phone_match_candidates(tenant.phone) + phone_match_candidates(tenant.mobile)
            if candidate in tenant_candidates and tenant.id is not None:
                tenant_matches.append(tenant)
        if len(tenant_matches) > 1:
            logger.warning("Ambiguous inbound WhatsApp phone match candidate=%s tenant_ids=%s", candidate, [tenant.id for tenant in tenant_matches])
            return None, candidate, matched_tenants
        if len(tenant_matches) == 1:
            tenant = tenant_matches[0]
            matched_tenants[tenant.id] = tenant
            matched_value = candidate
    if len(matched_tenants) == 1:
        tenant = next(iter(matched_tenants.values()))
        return tenant, matched_value, matched_tenants
    if len(matched_tenants) > 1:
        logger.warning("Ambiguous inbound WhatsApp phone match tenant_ids=%s", sorted(matched_tenants.keys()))
    return None, matched_value, matched_tenants


def resolve_tenant_for_inbound_channel(db: Session, payload: dict[str, Any], request_headers: dict[str, str], query_params: dict[str, str]) -> RoutingResult:
    provider = _first_non_empty(payload.get("provider"), query_params.get("provider"), request_headers.get("x-provider"), request_headers.get("X-Provider"))
    external_account_id = _first_non_empty(payload.get("external_account_id"), payload.get("whatsapp_client_id"), query_params.get("external_account_id"), request_headers.get("x-external-account-id"), request_headers.get("X-External-Account-Id"))
    webhook_token = _first_non_empty(payload.get("webhook_token"), request_headers.get("x-webhook-token"), request_headers.get("X-Webhook-Token"), query_params.get("webhook_token"))
    external_phone_id = _first_non_empty(payload.get("external_phone_id"), query_params.get("external_phone_id"))
    chat_namespace = _first_non_empty(payload.get("external_chat_namespace"), payload.get("whatsapp_chat_id"))
    inbound_phone_candidates = _normalized_phone_candidates(
        payload.get("sender_normalized"),
        payload.get("sender"),
        payload.get("from"),
        payload.get("sender_raw"),
        payload.get("whatsapp_chat_id"),
    )

    if webhook_token:
        endpoint = db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.webhook_token == webhook_token, TenantChannelEndpoint.is_active.is_(True)).first()
        if endpoint:
            tenant = db.query(Tenant).filter(Tenant.id == endpoint.tenant_id).first()
            if tenant:
                logger.info("Resolved inbound tenant by webhook_token")
                return RoutingResult(tenant=tenant, strategy="webhook_token", matched_value=endpoint.webhook_token)

    logger.info("Inbound WhatsApp normalized phone candidates: %s", inbound_phone_candidates)
    if _is_whatsapp_provider(provider) and inbound_phone_candidates:
        tenant, matched_value, matched_tenants = _match_phone_tenant(db, inbound_phone_candidates)
        if tenant is not None:
            logger.info("Resolved inbound tenant by whatsapp_phone_match tenant_id=%s matched_value=%s", tenant.id, matched_value)
            return RoutingResult(tenant=tenant, strategy="whatsapp_phone_match", matched_value=matched_value)
        if matched_tenants:
            return RoutingResult(tenant=None, strategy="ambiguous_phone_match", matched_value=matched_value)

    if provider and external_account_id:
        if _is_whatsapp_provider(provider):
            logger.info("Skipping provider+external_account_id tenant resolution for shared WhatsApp provider=%s external_account_id=%s", provider, external_account_id)
        else:
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
                    logger.info("Resolved inbound tenant by provider+external_account_id fallback")
                    return RoutingResult(tenant=tenant, strategy="provider_external_account_id", matched_value=external_account_id)

    legacy_sources = [
        payload.get("recipient"),
        payload.get("to"),
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

    candidates = _normalized_phone_candidates(*legacy_sources)

    if candidates:
        tenant, matched_value, matched_tenants = _match_phone_tenant(db, candidates)
        if tenant is not None:
            logger.info("Resolved inbound tenant by legacy_phone_inference tenant_id=%s matched_value=%s", tenant.id, matched_value)
            return RoutingResult(tenant=tenant, strategy="legacy_phone_inference", matched_value=matched_value)
        if matched_tenants:
            return RoutingResult(tenant=None, strategy="ambiguous_phone_match", matched_value=matched_value)

    return RoutingResult(tenant=None, strategy="unresolved")
