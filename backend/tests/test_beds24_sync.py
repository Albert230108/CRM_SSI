import asyncio

from app.models.finance import Finance
from app.models.tenant import Tenant
from app.services import beds24_sync


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
