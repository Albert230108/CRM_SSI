"""Regression coverage for A2: the tenant finance endpoint must surface the
per-line Beds24 invoice-item status that is now persisted on the finances table.
Before this change Finance had no status column and the endpoint dropped it."""
from app.models.finance import Finance
from app.models.tenant import Tenant


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Finance Tenant", booking_id="B-fin-status")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _add_finance(db_session, tenant_id, **overrides):
    defaults = dict(tenant_id=tenant_id, type="charge", amount="100.00", currency="EUR", description="Room")
    defaults.update(overrides)
    row = Finance(**defaults)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_finance_endpoint_returns_persisted_status(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    _add_finance(db_session, tenant.id, type="charge", status="paid", description="Accommodation")
    _add_finance(db_session, tenant.id, type="payment", amount="50.00", status="unpaid", description="Deposit")

    response = non_admin_client.get(f"/api/tenants/{tenant.id}/finance")
    assert response.status_code == 200
    data = response.json()
    assert [c["status"] for c in data["charges"]] == ["paid"]
    assert [p["status"] for p in data["payments"]] == ["unpaid"]


def test_finance_endpoint_status_is_null_when_absent(non_admin_client, db_session):
    tenant = _create_tenant(db_session, booking_id="B-fin-nostatus")
    _add_finance(db_session, tenant.id, type="charge", status=None, description="Legacy row")

    response = non_admin_client.get(f"/api/tenants/{tenant.id}/finance")
    assert response.status_code == 200
    charges = response.json()["charges"]
    assert len(charges) == 1
    assert charges[0]["status"] is None
