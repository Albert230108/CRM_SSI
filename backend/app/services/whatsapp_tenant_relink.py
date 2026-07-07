from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.phone_normalization import phone_match_candidates
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.services.tenant_phone_aliases import build_tenant_phone_candidate_map


@dataclass(frozen=True)
class WhatsAppTenantRelinkResult:
    communication_id: int
    from_tenant_id: int
    to_tenant_id: int
    matched_value: str | None
    match_reason: str


def _safe_whatsapp_phone_candidates(*values: str | None) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        raw = value.strip().lower()
        if not raw:
            continue
        if raw.endswith("@g.us") or raw.endswith("@lid"):
            continue
        if "@" in raw and not raw.endswith("@c.us"):
            continue
        for candidate in phone_match_candidates(raw):
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
    return candidates


def _iter_matching_tenants(db: Session, phone_candidates: Iterable[str]) -> list[Tenant]:
    tenant_lookup = {tenant.id: tenant for tenant in db.query(Tenant).all() if tenant.id is not None}
    tenant_candidates_by_id = build_tenant_phone_candidate_map(db)
    matched: dict[int, Tenant] = {}
    matched_value: str | None = None

    for candidate in phone_candidates:
        tenant_matches: list[Tenant] = []
        for tenant_id, tenant in tenant_lookup.items():
            tenant_candidates = tenant_candidates_by_id.get(tenant_id, [])
            if candidate in tenant_candidates:
                tenant_matches.append(tenant)
        if len(tenant_matches) == 1:
            tenant = tenant_matches[0]
            matched[tenant.id] = tenant
            matched_value = candidate
        elif len(tenant_matches) > 1:
            email_matches = [tenant for tenant in tenant_matches if (tenant.email or "").strip()]
            if len(email_matches) == 1:
                tenant = email_matches[0]
                matched[tenant.id] = tenant
                matched_value = candidate

    return list(matched.values())


def relink_whatsapp_communications_to_email_tenant(db: Session, *, tenant_id: int | None = None, apply: bool = False, limit: int | None = None) -> list[WhatsAppTenantRelinkResult]:
    query = (
        db.query(Communication)
        .filter(Communication.channel == "whatsapp")
        .filter(Communication.tenant_id.isnot(None))
        .order_by(Communication.created_at.asc(), Communication.id.asc())
    )
    if tenant_id is not None:
        query = query.filter(Communication.tenant_id == tenant_id)
    if limit is not None:
        query = query.limit(limit)

    results: list[WhatsAppTenantRelinkResult] = []
    for communication in query.all():
        current_tenant = db.query(Tenant).filter(Tenant.id == communication.tenant_id).first()
        if current_tenant is None:
            continue

        phone_candidates = _safe_whatsapp_phone_candidates(
            communication.whatsapp_normalized_phone,
            communication.whatsapp_identity_key,
            communication.whatsapp_chat_id,
            communication.external_chat_namespace,
        )
        if not phone_candidates:
            continue

        matching_tenants = _iter_matching_tenants(db, phone_candidates)
        if not matching_tenants:
            continue

        if len(matching_tenants) == 1:
            target_tenant = matching_tenants[0]
            reason = "single_alias_match"
        else:
            email_matches = [tenant for tenant in matching_tenants if (tenant.email or "").strip()]
            if len(email_matches) != 1:
                continue
            target_tenant = email_matches[0]
            reason = "email_bearing_alias_match"

        if target_tenant.id == current_tenant.id:
            continue

        results.append(
            WhatsAppTenantRelinkResult(
                communication_id=communication.id,
                from_tenant_id=current_tenant.id,
                to_tenant_id=target_tenant.id,
                matched_value=phone_candidates[0] if phone_candidates else None,
                match_reason=reason,
            )
        )
        if apply:
            communication.tenant_id = target_tenant.id

    if apply and results:
        db.commit()
    elif not apply:
        db.rollback()

    return results
