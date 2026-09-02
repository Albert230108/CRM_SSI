from tests.conftest import ADMIN_USER


def _auth_headers_for(tenant_id, booking_id):
    from app.core.quotation_token import create_quotation_token

    token = create_quotation_token(tenant_id=tenant_id, booking_id=booking_id, issued_by_user_id=ADMIN_USER.id)
    return {"Authorization": f"Bearer {token}"}


def test_booking_group_endpoint_returns_master_and_members(client, monkeypatch):
    import app.api.quotation as quotation_module

    async def fake_group(booking_id):
        return [
            {"id": "100", "bookingGroup": {"master": "100", "ids": ["100", "101"]}, "roomName": "Studio 1"},
            {"id": "101", "bookingGroup": {"master": "100", "ids": ["100", "101"]}, "roomName": "Studio 2"},
        ]

    monkeypatch.setattr(quotation_module, "fetch_booking_group", fake_group)

    headers = _auth_headers_for(1, "100")
    response = client.get("/api/quotation/beds24-booking-group/100", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["master_id"] == "100"
    assert len(body["bookings"]) == 2


def test_booking_group_endpoint_requires_token(client):
    response = client.get("/api/quotation/beds24-booking-group/100")
    assert response.status_code == 401
