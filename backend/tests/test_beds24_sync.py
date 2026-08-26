import asyncio

from app.models.finance import Finance
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_brain_entry import TenantBrainEntry
from app.services import beds24_sync, tenant_brain_service


async def fake_booking_fetch(booking_id):
    return {
        "id": booking_id,
        "roomName": "Studio 1",
        "firstName": "Sync",
        "lastName": "Tester",
        "arrival": "2026-07-01",
        "departure": "2026-07-08",
        "invoiceItems": [
            {"type": "charge", "amount": 65, "qty": 7, "currency": "EUR", "description": "Rent"},
        ],
    }


def test_sync_creates_tenant_and_finance_when_missing(db_session, monkeypatch):
    monkeypatch.setattr(beds24_sync, "fetch_booking_with_invoice", fake_booking_fetch)

    tenant = asyncio.run(beds24_sync.sync_tenant_from_beds24_booking(db_session, "SYNC-1"))
    db_session.commit()

    assert tenant is not None
    assert tenant.booking_id == "SYNC-1"
    assert tenant.first_name == "Sync"

    finances = db_session.query(Finance).filter(Finance.tenant_id == tenant.id).all()
    assert len(finances) == 1
    assert finances[0].type == "charge"


def test_sync_updates_existing_tenant_and_replaces_finance(db_session, monkeypatch):
    monkeypatch.setattr(beds24_sync, "fetch_booking_with_invoice", fake_booking_fetch)

    existing = Tenant(booking_id="SYNC-2", name="Old Name")
    db_session.add(existing)
    db_session.commit()
    db_session.add(Finance(tenant_id=existing.id, type="charge", amount=1, currency="EUR", description="Stale"))
    db_session.commit()

    tenant = asyncio.run(beds24_sync.sync_tenant_from_beds24_booking(db_session, "SYNC-2"))
    db_session.commit()

    assert tenant.id == existing.id
    assert tenant.first_name == "Sync"
    assert tenant.last_name == "Tester"
    finances = db_session.query(Finance).filter(Finance.tenant_id == tenant.id).all()
    assert len(finances) == 1
    assert finances[0].description == "Rent"


def test_sync_runs_initial_brain_scan_only_on_create(db_session, monkeypatch):
    """The initial-fill brain scan must fire once when a tenant is first created via Beds24
    sync, and never again on a later webhook update to that same tenant (a booking-detail
    change should not re-trigger the initial scan)."""
    from app.models.ai_agent_profile import BRAIN_WRITER_ROLE, AiAgentProfile
    from app.services import gemini_client

    db_session.add(AiAgentProfile(name="Default Brain Writer", role=BRAIN_WRITER_ROLE, is_default=True))
    db_session.commit()

    call_count = {"n": 0}

    def _fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        call_count["n"] += 1
        return gemini_client.GenerationResult(
            text="ignored",
            parsed={"should_remember": True, "entries": ["Booking-only initial fact."], "reasoning": "Initial scan."},
            model=model or "fake-model",
            prompt_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    monkeypatch.setattr(tenant_brain_service.gemini_client, "generate", _fake_generate)
    monkeypatch.setattr(beds24_sync, "fetch_booking_with_invoice", fake_booking_fetch)

    tenant = asyncio.run(beds24_sync.sync_tenant_from_beds24_booking(db_session, "SYNC-BRAIN-1"))
    db_session.commit()

    assert call_count["n"] == 1
    assert db_session.query(TenantBrainEntry).filter(TenantBrainEntry.tenant_id == tenant.id).count() == 1

    # A repeat sync of the same (now-existing) tenant must not re-trigger the initial scan.
    asyncio.run(beds24_sync.sync_tenant_from_beds24_booking(db_session, "SYNC-BRAIN-1"))
    db_session.commit()

    assert call_count["n"] == 1
    assert db_session.query(TenantBrainEntry).filter(TenantBrainEntry.tenant_id == tenant.id).count() == 1


def test_sync_seeds_formatter_default_for_a_newly_created_tenant(db_session, monkeypatch):
    from app.models.admin_settings import AdminSettings

    db_session.add(AdminSettings(formatter_default_enabled=True))
    db_session.commit()
    monkeypatch.setattr(beds24_sync, "fetch_booking_with_invoice", fake_booking_fetch)

    tenant = asyncio.run(beds24_sync.sync_tenant_from_beds24_booking(db_session, "SYNC-FMT-1"))
    db_session.commit()

    settings = db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).one()
    assert settings.formatter_enabled is True


def test_sync_returns_none_when_booking_not_found(db_session, monkeypatch):
    async def empty_fetch(booking_id):
        return {}

    monkeypatch.setattr(beds24_sync, "fetch_booking_with_invoice", empty_fetch)

    result = asyncio.run(beds24_sync.sync_tenant_from_beds24_booking(db_session, "SYNC-MISSING"))
    assert result is None


def test_sync_skips_creating_tenant_when_allow_create_false(db_session, monkeypatch):
    monkeypatch.setattr(beds24_sync, "fetch_booking_with_invoice", fake_booking_fetch)

    result = asyncio.run(
        beds24_sync.sync_tenant_from_beds24_booking(db_session, "SYNC-NEW-CANCEL", allow_create=False)
    )
    assert result is None
    assert db_session.query(Tenant).filter(Tenant.booking_id == "SYNC-NEW-CANCEL").first() is None


def test_sync_seeds_planner_default_for_a_newly_created_tenant(db_session, monkeypatch):
    """Regression test: sync_tenant_from_beds24_booking (the Quotation Manager's "send to
    Beds24" resync path) is one of the two tenant-creation paths that used to skip
    apply_default_planner_mode entirely, so a tenant created this way stayed stuck on "off"
    even when Admin Settings had a non-off planner default configured.
    """
    from app.models.admin_settings import AdminSettings
    from app.models.tenant_ai_settings import TenantAiSettings

    db_session.add(AdminSettings(planner_default_mode="auto-draft"))
    db_session.commit()

    monkeypatch.setattr(beds24_sync, "fetch_booking_with_invoice", fake_booking_fetch)

    tenant = asyncio.run(beds24_sync.sync_tenant_from_beds24_booking(db_session, "SYNC-PLANNER-DEFAULT"))
    db_session.commit()

    settings = db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    assert settings is not None
    assert settings.planner_mode == "auto-draft"


def test_sync_does_not_retrofit_planner_mode_for_an_existing_tenant(db_session, monkeypatch):
    """An existing tenant's planner_mode must never be overwritten by a later sync - switching
    the admin default cannot silently start drafting for bookings already in flight, and an
    operator may have deliberately turned the planner off for this specific tenant.
    """
    from app.models.admin_settings import AdminSettings
    from app.models.tenant_ai_settings import TenantAiSettings

    db_session.add(AdminSettings(planner_default_mode="auto-draft"))
    existing = Tenant(booking_id="SYNC-PLANNER-EXISTING", name="Old Name")
    db_session.add(existing)
    db_session.commit()
    db_session.add(TenantAiSettings(tenant_id=existing.id, planner_mode="off"))
    db_session.commit()

    monkeypatch.setattr(beds24_sync, "fetch_booking_with_invoice", fake_booking_fetch)

    asyncio.run(beds24_sync.sync_tenant_from_beds24_booking(db_session, "SYNC-PLANNER-EXISTING"))
    db_session.commit()

    settings = db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == existing.id).first()
    assert settings.planner_mode == "off"
