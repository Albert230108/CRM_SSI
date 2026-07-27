from app.models.finance import Finance
from app.models.tenant import Tenant


async def fake_booking_fetch(booking_id):
    return {
        "id": booking_id,
        "roomName": "Studio 1",
        "firstName": "Noti",
        "lastName": "Fier",
        "arrival": "2026-08-01",
        "departure": "2026-08-05",
        "invoiceItems": [
            {"type": "charge", "amount": 100, "qty": 1, "currency": "EUR", "description": "Room charge"},
            {"type": "payment", "amount": 50, "qty": 1, "currency": "EUR", "description": "Deposit"},
        ],
    }


def test_booking_notifier_get_is_accepted_and_upserts_tenant(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)

    response = client.get("/api/webhooks/beds24", params={"bookid": "NOTI-1", "status": "modify"})

    assert response.status_code == 200
    assert response.json()["booking_id"] == "NOTI-1"

    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "NOTI-1").first()
    assert tenant is not None
    assert tenant.first_name == "Noti"

    finances = db_session.query(Finance).filter(Finance.tenant_id == tenant.id).all()
    assert {f.type for f in finances} == {"charge", "payment"}


def test_booking_notifier_repeated_identical_pings_both_process(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)

    first = client.get("/api/webhooks/beds24", params={"bookid": "NOTI-2", "status": "modify"})
    second = client.get("/api/webhooks/beds24", params={"bookid": "NOTI-2", "status": "modify"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json().get("detail") != "duplicate delivery ignored"

    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "NOTI-2").first()
    finances = db_session.query(Finance).filter(Finance.tenant_id == tenant.id).all()
    assert {f.type for f in finances} == {"charge", "payment"}


def test_booking_notifier_cancel_for_unknown_booking_is_ignored(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)

    response = client.get("/api/webhooks/beds24", params={"bookid": "NOTI-CANCEL", "status": "cancel"})

    assert response.status_code == 200
    assert response.json()["detail"] == "cancellation for unknown booking, skipped"
    assert db_session.query(Tenant).filter(Tenant.booking_id == "NOTI-CANCEL").first() is None
