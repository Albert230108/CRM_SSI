import logging
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.phone_normalization import phone_match_candidates
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services.tenant_phone_aliases import get_tenant_phone_identity_maps

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutingResult:
    tenant: Tenant | None
    strategy: str
    matched_value: str | None = None
    matched_field: str | None = None
    unresolved_reason: str | None = None
    # The specific TenantChannelEndpoint (the manual chat link) this inbound message matched,
    # when the strategy resolved through one. Threaded onto the auto-draft trigger so a later
    # auto-send knows exactly which chat to reply in, instead of guessing when a tenant has
    # more than one active WhatsApp endpoint.
    matched_endpoint_id: int | None = None


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


def _normalized_phone_candidates(*values: Any) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, str) and value.strip().lower().endswith("@g.us"):
            continue
        for candidate in phone_match_candidates(value if isinstance(value, str) else None):
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
    return candidates


def _is_whatsapp_provider(provider: str | None) -> bool:
    return bool(provider and provider.strip().lower().startswith("whatsapp"))


def _lookup_whatsapp_endpoint_by_account_identity(db: Session, provider: str, external_account_id: str) -> TenantChannelEndpoint | None:
    if not provider or not external_account_id:
        return None
    return (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.provider == provider,
            TenantChannelEndpoint.external_account_id == external_account_id,
            TenantChannelEndpoint.is_active.is_(True),
        )
        .first()
    )


def _normalize_chat_identity_for_comparison(value: str | None) -> str | None:
    """Normalize WhatsApp chat identity by stripping provider suffixes for comparison.

    Treats @lid, @c.us, @g.us as equivalent bases. For example:
    - '326472368@lid' → '326472368'
    - '326472368@c.us' → '326472368'
    - '123456-456789@g.us' → '123456-456789'
    """
    if not value:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    for suffix in ("@c.us", "@g.us", "@lid"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)] or None
    return normalized


def _lookup_whatsapp_endpoint_by_exact_chat_identity(
    db: Session,
    *,
    provider: str,
    external_account_id: str,
    chat_identity: str,
) -> TenantChannelEndpoint | None:
    if not provider or not external_account_id or not chat_identity:
        return None
    return (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.provider == provider,
            TenantChannelEndpoint.external_account_id == external_account_id,
            TenantChannelEndpoint.external_chat_namespace == chat_identity,
            TenantChannelEndpoint.is_active.is_(True),
        )
        .first()
    )


def _lookup_whatsapp_endpoint_by_normalized_chat_identity(
    db: Session,
    *,
    provider: str,
    external_account_id: str,
    chat_identity: str,
) -> TenantChannelEndpoint | None:
    """Lookup endpoint by normalizing both payload and endpoint chat identities.

    Used when the webhook payload doesn't include external_chat_namespace directly
    but provides whatsapp_chat_id. Normalizes both to compare core IDs, handling
    @lid vs @c.us format variations.
    """
    if not provider or not external_account_id or not chat_identity:
        return None
    normalized_payload_chat = _normalize_chat_identity_for_comparison(chat_identity)
    if not normalized_payload_chat:
        return None

    # Find active endpoints for this account
    endpoints = (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.provider == provider,
            TenantChannelEndpoint.external_account_id == external_account_id,
            TenantChannelEndpoint.is_active.is_(True),
            TenantChannelEndpoint.external_chat_namespace.isnot(None),
        )
        .all()
    )

    for endpoint in endpoints:
        normalized_endpoint_chat = _normalize_chat_identity_for_comparison(endpoint.external_chat_namespace)
        if normalized_endpoint_chat == normalized_payload_chat:
            return endpoint

    return None


def _whatsapp_endpoints_for_account_identity(db: Session, provider: str, external_account_id: str) -> list[TenantChannelEndpoint]:
    if not provider or not external_account_id:
        return []
    return (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.provider == provider,
            TenantChannelEndpoint.external_account_id == external_account_id,
            TenantChannelEndpoint.is_active.is_(True),
        )
        .all()
    )

def _match_phone_tenant(db: Session, candidates: list[str]) -> tuple[Tenant | None, str | None, dict[int, Tenant]]:
    matched_tenants: dict[int, Tenant] = {}
    matched_value: str | None = None
    identity_maps = get_tenant_phone_identity_maps(db)
    tenant_candidates_by_id = identity_maps.candidate_map
    tenant_lookup = identity_maps.tenant_lookup
    for candidate in candidates:
        tenant_matches: list[Tenant] = []
        for tenant_id, tenant in tenant_lookup.items():
            tenant_candidates = tenant_candidates_by_id.get(tenant_id, [])
            if candidate in tenant_candidates:
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
    explicit_tenant_id = _first_non_empty(payload.get("tenant_id"), query_params.get("tenant_id"), request_headers.get("x-tenant-id"), request_headers.get("X-Tenant-Id"))
    webhook_token = _first_non_empty(payload.get("webhook_token"), request_headers.get("x-webhook-token"), request_headers.get("X-Webhook-Token"), query_params.get("webhook_token"))
    external_phone_id = _first_non_empty(payload.get("external_phone_id"), query_params.get("external_phone_id"))
    chat_identity = _first_non_empty(payload.get("external_chat_namespace"), payload.get("whatsapp_chat_id"))
    source = _first_non_empty(payload.get("source"))
    is_history_payload = bool(source and source.strip().lower() in {"history", "backfill"})
    inbound_phone_candidates = _normalized_phone_candidates(
        payload.get("sender_normalized"),
        payload.get("sender"),
        payload.get("from"),
        payload.get("sender_raw"),
        payload.get("whatsapp_normalized_phone"),
        payload.get("recipient_normalized"),
        payload.get("recipient"),
        payload.get("to"),
    )

    if explicit_tenant_id:
        try:
            tenant_lookup_id = int(str(explicit_tenant_id).strip())
        except (TypeError, ValueError):
            tenant_lookup_id = None
        if tenant_lookup_id is not None:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_lookup_id).first()
            if tenant:
                logger.info("Resolved inbound tenant by explicit_tenant_id tenant_id=%s", tenant.id)
                return RoutingResult(tenant=tenant, strategy="explicit_tenant_id", matched_value=str(explicit_tenant_id), matched_field="tenant_id")

    if webhook_token:
        endpoint = db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.webhook_token == webhook_token, TenantChannelEndpoint.is_active.is_(True)).first()
        if endpoint:
            tenant = db.query(Tenant).filter(Tenant.id == endpoint.tenant_id).first()
            if tenant:
                logger.info("Resolved inbound tenant by webhook_token tenant_id=%s", tenant.id)
                return RoutingResult(tenant=tenant, strategy="webhook_token", matched_value=endpoint.webhook_token, matched_field="webhook_token", matched_endpoint_id=endpoint.id)

    logger.info("Inbound WhatsApp normalized phone candidates: %s", inbound_phone_candidates)
    if provider and external_account_id:
        active_endpoints_for_account = _whatsapp_endpoints_for_account_identity(db, provider, external_account_id)
        if chat_identity:
            endpoint = _lookup_whatsapp_endpoint_by_exact_chat_identity(
                db,
                provider=provider,
                external_account_id=external_account_id,
                chat_identity=chat_identity,
            )
            if endpoint:
                tenant = db.query(Tenant).filter(Tenant.id == endpoint.tenant_id).first()
                if tenant:
                    logger.info(
                        "Resolved inbound tenant by exact_chat_endpoint tenant_id=%s provider=%s external_account_id=%s chat_identity=%s history=%s",
                        tenant.id,
                        provider,
                        external_account_id,
                        chat_identity,
                        is_history_payload,
                    )
                    return RoutingResult(
                        tenant=tenant,
                        strategy="exact_chat_endpoint",
                        matched_value=chat_identity,
                        matched_field="provider+external_account_id+external_chat_namespace",
                        matched_endpoint_id=endpoint.id,
                    )

            # Fallback: Try normalized chat identity matching (handles @lid vs @c.us variants).
            # Used when webhook payload doesn't include external_chat_namespace but does
            # include whatsapp_chat_id (e.g., history backfill payloads from WhatsApp service).
            normalized_endpoint = _lookup_whatsapp_endpoint_by_normalized_chat_identity(
                db,
                provider=provider,
                external_account_id=external_account_id,
                chat_identity=chat_identity,
            )
            if normalized_endpoint:
                tenant = db.query(Tenant).filter(Tenant.id == normalized_endpoint.tenant_id).first()
                if tenant:
                    logger.info(
                        "Resolved inbound tenant by normalized_chat_endpoint tenant_id=%s provider=%s external_account_id=%s chat_identity=%s history=%s",
                        tenant.id,
                        provider,
                        external_account_id,
                        chat_identity,
                        is_history_payload,
                    )
                    return RoutingResult(
                        tenant=tenant,
                        strategy="normalized_chat_endpoint",
                        matched_value=chat_identity,
                        matched_field="provider+external_account_id+normalized_chat_id",
                        matched_endpoint_id=normalized_endpoint.id,
                    )

            if active_endpoints_for_account:
                logger.warning(
                    "Unresolved inbound WhatsApp: no exact chat endpoint match provider=%s external_account_id=%s chat_identity=%s history=%s",
                    provider,
                    external_account_id,
                    chat_identity,
                    is_history_payload,
                )
                return RoutingResult(
                    tenant=None,
                    strategy="unresolved",
                    matched_value=chat_identity,
                    matched_field="provider+external_account_id+external_chat_namespace",
                    unresolved_reason="no_exact_chat_match",
                )
        else:
            if active_endpoints_for_account:
                allow_account_fallback = os.getenv("CRM_WHATSAPP_ALLOW_ACCOUNT_LEVEL_ENDPOINT_FALLBACK", "").strip().lower() in {"1", "true", "yes"}
                if allow_account_fallback:
                    if len(active_endpoints_for_account) == 1:
                        endpoint = active_endpoints_for_account[0]
                        if not _first_non_empty(endpoint.external_chat_namespace):
                            tenant = db.query(Tenant).filter(Tenant.id == endpoint.tenant_id).first()
                            if tenant:
                                logger.warning(
                                    "Resolved inbound tenant by account_identity_fallback tenant_id=%s provider=%s external_account_id=%s history=%s",
                                    tenant.id,
                                    provider,
                                    external_account_id,
                                    is_history_payload,
                                )
                                return RoutingResult(
                                    tenant=tenant,
                                    strategy="account_identity_fallback",
                                    matched_value=external_account_id,
                                    matched_field="provider+external_account_id",
                                    matched_endpoint_id=endpoint.id,
                                )

                        logger.warning(
                            "Unresolved inbound WhatsApp: missing_chat_identity provider=%s external_account_id=%s history=%s",
                            provider,
                            external_account_id,
                            is_history_payload,
                        )
                        return RoutingResult(
                            tenant=None,
                            strategy="missing_chat_identity",
                            matched_value=external_account_id,
                            matched_field="provider+external_account_id",
                            unresolved_reason="missing_chat_identity",
                        )

                    logger.warning(
                        "Unresolved inbound WhatsApp: ambiguous_account_identity provider=%s external_account_id=%s endpoints=%s history=%s",
                        provider,
                        external_account_id,
                        len(active_endpoints_for_account),
                        is_history_payload,
                    )
                    return RoutingResult(
                        tenant=None,
                        strategy="ambiguous_account_identity",
                        matched_value=external_account_id,
                        matched_field="provider+external_account_id",
                        unresolved_reason="ambiguous_account_identity",
                    )

                logger.warning(
                    "Unresolved inbound WhatsApp: missing_chat_identity provider=%s external_account_id=%s history=%s",
                    provider,
                    external_account_id,
                    is_history_payload,
                )
                return RoutingResult(
                    tenant=None,
                    strategy="missing_chat_identity",
                    matched_value=external_account_id,
                    matched_field="provider+external_account_id",
                    unresolved_reason="missing_chat_identity",
                )

    if _is_whatsapp_provider(provider) and inbound_phone_candidates:
        tenant, matched_value, matched_tenants = _match_phone_tenant(db, inbound_phone_candidates)
        if tenant is not None:
            logger.info("Resolved inbound tenant by whatsapp_phone_match tenant_id=%s matched_value=%s", tenant.id, matched_value)
            return RoutingResult(tenant=tenant, strategy="whatsapp_phone_match", matched_value=matched_value, matched_field="phone")
        if matched_tenants:
            logger.warning("Ambiguous inbound WhatsApp phone match tenant_ids=%s", sorted(matched_tenants.keys()))
            return RoutingResult(tenant=None, strategy="ambiguous_phone_match", matched_value=matched_value, matched_field="phone", unresolved_reason="ambiguous_phone_match")

    legacy_sources = [
        payload.get("recipient"),
        payload.get("to"),
        chat_identity,
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
                return RoutingResult(tenant=tenant, strategy=f"legacy_email:{email_key}", matched_value=value, matched_field=email_key)

    candidates = _normalized_phone_candidates(*legacy_sources)

    if candidates:
        tenant, matched_value, matched_tenants = _match_phone_tenant(db, candidates)
        if tenant is not None:
            logger.info("Resolved inbound tenant by legacy_phone_inference tenant_id=%s matched_value=%s", tenant.id, matched_value)
            return RoutingResult(tenant=tenant, strategy="legacy_phone_inference", matched_value=matched_value, matched_field="phone")
        if matched_tenants:
            logger.warning("Ambiguous inbound WhatsApp phone match tenant_ids=%s", sorted(matched_tenants.keys()))
            return RoutingResult(tenant=None, strategy="ambiguous_phone_match", matched_value=matched_value, matched_field="phone", unresolved_reason="ambiguous_phone_match")

    return RoutingResult(tenant=None, strategy="unresolved", unresolved_reason="no_deterministic_match")
