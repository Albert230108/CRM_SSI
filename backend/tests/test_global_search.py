"""Regression tests for the global cross-entity search endpoint (GET /api/search)."""

from app.models.brain_section import BrainSection
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_brain_entry import TenantBrainEntry
from app.models.working_memory_rule import WorkingMemoryRule

# A nonsense token that will not collide with any incidental fixture text.
TERM = "Wozzleplex"


def _seed(db_session, suffix):
    # Unique keys per call: db_session.commit() persists to the shared SQLite test DB across
    # tests in this suite, so the unique-constrained booking_id / brain path must not collide.
    tenant = Tenant(booking_id=f"BK-SEARCH-{suffix}", name=f"{TERM} Guesthouse")
    db_session.add(tenant)
    db_session.flush()  # assign tenant.id for the tenant-linked rows below

    db_session.add(
        Communication(
            tenant_id=tenant.id,
            channel="email",
            direction="inbound",
            subject="Booking question",
            message=f"Please confirm the {TERM} rate for next week.",
        )
    )
    db_session.add(
        BrainSection(
            path=f"policies.search-{suffix}",
            slug=f"search-{suffix}",
            title="Cancellation policy",
            content=f"Refunds follow the {TERM} rule when cancelled early.",
        )
    )
    db_session.add(
        TenantBrainEntry(
            tenant_id=tenant.id,
            content=f"Guest prefers the {TERM} suite.",
            source="manual",
        )
    )
    db_session.add(
        WorkingMemoryRule(
            condition_text="When a guest asks about parking",
            action_text=f"Mention the {TERM} garage next door.",
        )
    )
    db_session.commit()
    return tenant


def test_search_requires_auth(client):
    # The default `client` fixture overrides only get_current_admin_user, so the real
    # get_current_user runs on this endpoint and rejects the unauthenticated request.
    response = client.get("/api/search", params={"q": TERM})
    assert response.status_code == 401


def test_search_finds_matches_across_entity_types(non_admin_client, db_session):
    tenant = _seed(db_session, "across")

    response = non_admin_client.get("/api/search", params={"q": TERM})
    assert response.status_code == 200
    results = response.json()

    by_type = {r["type"] for r in results}
    assert {"tenant", "communication", "brain_section", "tenant_brain_entry", "working_memory_rule"} <= by_type

    # Every result carries a snippet, and the matched text surfaces in it.
    assert all(r["snippet"] for r in results)
    assert any(TERM in r["snippet"] for r in results)

    tenant_hit = next(r for r in results if r["type"] == "tenant")
    assert tenant_hit["id"] == tenant.id
    assert tenant_hit["tenant_id"] == tenant.id

    # Tenant-linked rows expose tenant_id for deep-linking; global rows do not.
    entry_hit = next(r for r in results if r["type"] == "tenant_brain_entry")
    assert entry_hit["tenant_id"] == tenant.id
    rule_hit = next(r for r in results if r["type"] == "working_memory_rule")
    assert rule_hit["tenant_id"] is None


def test_search_is_case_insensitive(non_admin_client, db_session):
    _seed(db_session, "case")
    response = non_admin_client.get("/api/search", params={"q": TERM.lower()})
    assert response.status_code == 200
    assert response.json(), "case-insensitive query should still match"


def test_types_filter_restricts_results(non_admin_client, db_session):
    _seed(db_session, "filter")

    response = non_admin_client.get("/api/search", params={"q": TERM, "types": ["tenant"]})
    assert response.status_code == 200
    results = response.json()
    assert results, "expected at least the tenant hit"
    assert {r["type"] for r in results} == {"tenant"}


def test_blank_query_returns_no_results(non_admin_client, db_session):
    _seed(db_session, "blank")
    response = non_admin_client.get("/api/search", params={"q": "   "})
    assert response.status_code == 200
    assert response.json() == []
