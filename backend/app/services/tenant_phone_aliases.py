from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.phone_normalization import normalize_phone, phone_match_candidates
from app.models.tenant import Tenant
from app.models.tenant_phone_alias import TenantPhoneAlias


@dataclass(frozen=True)
class TenantPhoneAliasWrite:
    raw_phone: str
    normalized_phone: str
    is_primary: bool
    source: str | None = None


@dataclass(frozen=True)
class TenantPhoneIdentityMaps:
    tenant_lookup: dict[int, Tenant]
    candidate_map: dict[int, list[str]]


_TENANT_PHONE_IDENTITY_MAPS_CACHE: tuple[float, TenantPhoneIdentityMaps] | None = None
_TENANT_PHONE_IDENTITY_MAPS_CACHE_TTL_SECONDS = 30.0


def _normalize_raw_phone(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return raw or None


def _build_phone_alias_writes(phone_sources: Iterable[tuple[str | None, str | None]]) -> list[TenantPhoneAliasWrite]:
    writes: list[TenantPhoneAliasWrite] = []
    seen: set[str] = set()
    for raw_phone, source in phone_sources:
        normalized_raw_phone = _normalize_raw_phone(raw_phone)
        normalized_phone = normalize_phone(normalized_raw_phone)
        if not normalized_phone or normalized_phone in seen:
            continue
        seen.add(normalized_phone)
        writes.append(
            TenantPhoneAliasWrite(
                raw_phone=normalized_raw_phone or normalized_phone,
                normalized_phone=normalized_phone,
                is_primary=not writes,
                source=source,
            )
        )
    return writes


def sync_tenant_phone_aliases(
    db: Session,
    tenant: Tenant,
    *,
    primary_phone: str | None = None,
    alias_phones: Iterable[str | None] = (),
    primary_source: str | None = "tenant.phone",
    alias_source: str | None = "tenant.mobile",
) -> None:
    if tenant.id is None:
        raise ValueError("tenant must be persisted before syncing phone aliases")

    phone_sources: list[tuple[str | None, str | None]] = []
    if primary_phone is not None:
        phone_sources.append((primary_phone, primary_source))
    for alias_phone in alias_phones:
        phone_sources.append((alias_phone, alias_source))

    writes = _build_phone_alias_writes(phone_sources)
    db.query(TenantPhoneAlias).filter(TenantPhoneAlias.tenant_id == tenant.id).delete(synchronize_session=False)
    for phone_write in writes:
        db.add(
            TenantPhoneAlias(
                tenant_id=tenant.id,
                normalized_phone=phone_write.normalized_phone,
                raw_phone=phone_write.raw_phone,
                is_primary=phone_write.is_primary,
                source=phone_write.source,
            )
        )
    invalidate_tenant_phone_identity_maps_cache()


def get_tenant_phone_alias_rows(db: Session, tenant_id: int) -> list[TenantPhoneAlias]:
    return (
        db.query(TenantPhoneAlias)
        .filter(TenantPhoneAlias.tenant_id == tenant_id)
        .order_by(TenantPhoneAlias.is_primary.desc(), TenantPhoneAlias.id.asc())
        .all()
    )


def invalidate_tenant_phone_identity_maps_cache() -> None:
    global _TENANT_PHONE_IDENTITY_MAPS_CACHE
    _TENANT_PHONE_IDENTITY_MAPS_CACHE = None


def _build_tenant_phone_identity_maps(db: Session) -> TenantPhoneIdentityMaps:
    tenants = [tenant for tenant in db.query(Tenant).all() if tenant.id is not None]
    alias_rows = db.query(TenantPhoneAlias).order_by(TenantPhoneAlias.tenant_id.asc(), TenantPhoneAlias.is_primary.desc(), TenantPhoneAlias.id.asc()).all()

    aliases_by_tenant_id: dict[int, list[str]] = {}
    for alias in alias_rows:
        aliases_by_tenant_id.setdefault(alias.tenant_id, []).append(alias.normalized_phone)

    tenant_lookup: dict[int, Tenant] = {}
    candidate_map: dict[int, list[str]] = {}
    for tenant in tenants:
        if tenant.id is None:
            continue
        tenant_lookup[tenant.id] = tenant
        if tenant.id in aliases_by_tenant_id and aliases_by_tenant_id[tenant.id]:
            alias_candidates: list[str] = []
            seen_alias: set[str] = set()
            for normalized_phone in aliases_by_tenant_id[tenant.id]:
                for candidate in phone_match_candidates(normalized_phone):
                    if candidate not in seen_alias:
                        seen_alias.add(candidate)
                        alias_candidates.append(candidate)
            if alias_candidates:
                candidate_map[tenant.id] = alias_candidates
            continue

        candidates: list[str] = []
        seen: set[str] = set()
        for value in (tenant.phone, tenant.mobile):
            for candidate in phone_match_candidates(value):
                if candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
        if candidates:
            candidate_map[tenant.id] = candidates

    return TenantPhoneIdentityMaps(tenant_lookup=tenant_lookup, candidate_map=candidate_map)


def get_tenant_phone_identity_maps(db: Session, *, refresh: bool = False) -> TenantPhoneIdentityMaps:
    global _TENANT_PHONE_IDENTITY_MAPS_CACHE
    now = time.monotonic()
    if not refresh and _TENANT_PHONE_IDENTITY_MAPS_CACHE is not None:
        cached_at, cached_maps = _TENANT_PHONE_IDENTITY_MAPS_CACHE
        if now - cached_at < _TENANT_PHONE_IDENTITY_MAPS_CACHE_TTL_SECONDS:
            return cached_maps

    maps = _build_tenant_phone_identity_maps(db)
    _TENANT_PHONE_IDENTITY_MAPS_CACHE = (now, maps)
    return maps


def get_tenant_primary_phone_raw(db: Session, tenant: Tenant) -> str | None:
    alias_rows = get_tenant_phone_alias_rows(db, tenant.id) if tenant.id is not None else []
    for alias in alias_rows:
        if alias.is_primary and alias.raw_phone:
            return alias.raw_phone
    if alias_rows:
        first_alias = alias_rows[0]
        if first_alias.raw_phone:
            return first_alias.raw_phone
        if first_alias.normalized_phone:
            return first_alias.normalized_phone
    return (tenant.phone or tenant.mobile or "").strip() or None


def get_tenant_phone_candidates(db: Session, tenant: Tenant) -> list[str]:
    if tenant.id is not None:
        cached_candidates = get_tenant_phone_identity_maps(db).candidate_map.get(tenant.id)
        if cached_candidates:
            return list(cached_candidates)

    candidates: list[str] = []
    seen: set[str] = set()
    for value in (tenant.phone, tenant.mobile):
        for candidate in phone_match_candidates(value):
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
    return candidates


def build_tenant_phone_candidate_map(db: Session) -> dict[int, list[str]]:
    return get_tenant_phone_identity_maps(db).candidate_map
