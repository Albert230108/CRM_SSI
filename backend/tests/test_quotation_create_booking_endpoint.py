from app.models.tenant import Tenant
from tests.conftest import ADMIN_USER


async def fake_create_booking(booking_payload):
    # Assert the proxy translated snake_case -> Beds24 camelCase and dropped any id.
    assert "id" not in booking_payload
    assert booking_payload["roomId"] == 262377
    assert booking_payload["invoiceItems"][0]["vatRate"] == 9
    return "NEW-123"


async def fake_sync(db, booking_id, booking=None, allow_create=True):
    tenant = db.query(Tenant).filter(Tenant.booking_id == booking_id).first()
    if tenant is None:
        tenant = Tenant(booking_id=booking_id, name="Created Tenant")
        db.add(tenant)
        db.flush()
    return tenant


def _auth_headers_for(tenant_id, booking_id):
    from app.core.quotation_token import create_quotation_token

    token = create_quotation_token(tenant_id=tenant_id, booking_id=booking_id, issued_by_user_id=ADMIN_USER.id)
    return {"Authorization": f"Bearer {token}"}


def test_create_booking_endpoint_creates_and_syncs(client, db_session, monkeypatch):
    import app.api.quotation as quotation_module

    monkeypatch.setattr(quotation_module, "create_booking", fake_create_booking)
    monkeypatch.setattr(quotation_module, "sync_tenant_from_beds24_booking", fake_sync)

    headers = _auth_headers_for(1, None)
    response = client.post(
        "/api/quotation/beds24-booking",
        json={
            "room_id": 262377,
            "arrival": "2025-06-01",
            "departure": "2025-06-08",
            "status": "inquiry",
            "first_name": "Jane",
            "last_name": "Doe",
            "num_adults": 2,
            "invoice_items": [
                {"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["booking_id"] == "NEW-123"
    assert body["tenant_id"] is not None


def test_create_booking_endpoint_requires_token(client):
    response = client.post(
        "/api/quotation/beds24-booking",
        json={"room_id": 1, "arrival": "2025-06-01", "departure": "2025-06-08", "first_name": "Jane"},
    )
    assert response.status_code == 401
