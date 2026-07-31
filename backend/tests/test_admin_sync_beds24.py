"""
Regression test for Beds24 sync-all silently wiping tenant guest data.

_sync_beds24 updates tenants straight from the bulk-list booking dicts returned by
get_bookings(). Some of those items carry no guest details at all, so
_update_tenant_from_beds24 must not overwrite existing tenant fields with blanks just
because a given payload lacks them.
"""

from decimal import Decimal

import pytest

from app.api import admin_sync
from app.api.admin_sync import _update_tenant_from_beds24
from app.models.tenant import Tenant


def create_populated_tenant(db_session, booking_id="B-beds24-sync-test"):
    tenant = Tenant(
        name="Jane Doe",
        booking_id=booking_id,
        first_name="Jane",
        last_name="Doe",
        email="jane@example.com",
        phone="+1234567890",
        mobile="+1234567891",
        city="Lisbon",
        country="Portugal",
        address="123 Main St",
        company="Acme Inc",
        num_adults=2,
        num_children=1,
        total_price=Decimal("500.00"),
        currency="EUR",
        booking_status="Confirmed",
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_sparse_booking_detail_does_not_wipe_existing_guest_fields(db_session):
    """Fallback bulk-list item (no guestDetails) must not blank out existing tenant data."""
    tenant = create_populated_tenant(db_session)

    sparse_booking = {
        "id": tenant.booking_id,
        "status": 1,
        "firstName": "",
        "lastName": "",
        "email": "",
        "phone": "",
        "mobile": "",
        "guestDetails": {},
    }

    _update_tenant_from_beds24(db_session, tenant, sparse_booking)
    db_session.commit()
    db_session.refresh(tenant)

    assert tenant.first_name == "Jane"
    assert tenant.last_name == "Doe"
    assert tenant.email == "jane@example.com"
    assert tenant.phone == "+1234567890"
    assert tenant.mobile == "+1234567891"
    assert tenant.city == "Lisbon"
    assert tenant.country == "Portugal"
    assert tenant.address == "123 Main St"
    assert tenant.company == "Acme Inc"
    assert tenant.num_adults == 2
    assert tenant.num_children == 1
    assert tenant.total_price == Decimal("500.00")
    assert tenant.currency == "EUR"


def test_full_booking_detail_still_updates_fields(db_session):
    """A real payload with new data must still overwrite stale tenant fields."""
    tenant = create_populated_tenant(db_session)

    full_booking = {
        "id": tenant.booking_id,
        "status": 1,
        "firstName": "John",
        "lastName": "Smith",
        "email": "john@example.com",
        "phone": "+9876543210",
        "mobile": "+9876543211",
        "city": "Porto",
        "country": "Portugal",
        "numAdult": 3,
        "numChild": 0,
        "currency": "USD",
    }

    _update_tenant_from_beds24(db_session, tenant, full_booking)
    db_session.commit()
    db_session.refresh(tenant)

    assert tenant.first_name == "John"
    assert tenant.last_name == "Smith"
    assert tenant.email == "john@example.com"
    assert tenant.phone == "+9876543210"
    assert tenant.mobile == "+9876543211"
    assert tenant.city == "Porto"
    assert tenant.num_adults == 3
    assert tenant.currency == "USD"


@pytest.mark.asyncio
async def test_sync_beds24_does_not_refetch_each_booking(db_session, monkeypatch):
    """Regression: every GET /v2/bookings/{id} returned 500, so the per-booking detail fetch
    was pure cost - one failing sequential HTTPS round-trip per tenant - and the code silently
    fell back to the list item anyway. The list payload is now used directly."""
    tenant = create_populated_tenant(db_session, booking_id="B-no-refetch")

    async def fake_get_bookings():
        return [{"id": "B-no-refetch", "firstName": "Updated", "lastName": "Guest"}]

    monkeypatch.setattr(admin_sync, "get_bookings", fake_get_bookings)

    # The module must no longer reach for the single-booking endpoint at all.
    assert not hasattr(admin_sync, "get_booking_detail")

    updated = await admin_sync._sync_beds24(db_session, changed_by_user_id=None)

    db_session.refresh(tenant)
    assert updated == 1
    assert tenant.first_name == "Updated"
    assert tenant.last_name == "Guest"
