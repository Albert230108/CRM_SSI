def test_get_tenant_context_endpoint(client, auth_headers, monkeypatch):
    async def fake_get_tenant_context(tenant_id, token):
        assert tenant_id == 1
        assert token  # forwarded bearer token from the incoming request
        return {"tenant_id": 1, "booking_id": "12345", "room_name": "Studio 1"}

    import app.api.booking as booking_module

    monkeypatch.setattr(booking_module.crm_client, "get_tenant_context", fake_get_tenant_context)

    response = client.get("/api/booking/tenant-context/1", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"tenant_id": 1, "booking_id": "12345", "room_name": "Studio 1"}


def test_get_booking_endpoint(client, auth_headers, monkeypatch):
    async def fake_get_beds24_booking(booking_id, token):
        assert booking_id == "99999"
        return {"id": "99999", "roomName": "Studio 1"}

    import app.api.booking as booking_module

    monkeypatch.setattr(booking_module.crm_client, "get_beds24_booking", fake_get_beds24_booking)

    response = client.get("/api/booking/99999", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"id": "99999", "roomName": "Studio 1"}


def test_booking_endpoints_require_token(client):
    response = client.get("/api/booking/99999")
    assert response.status_code == 401

    response = client.get("/api/booking/tenant-context/1")
    assert response.status_code == 401


def test_get_booking_endpoint_accepts_tenant_less_token(client, monkeypatch):
    # Booking search has no per-tenant restriction, so the nav-bar's tenant-less
    # token (tenant_id=None) must work here too - only tenant-context is pinned.
    from tests.conftest import make_quotation_token

    async def fake_get_beds24_booking(booking_id, token):
        assert booking_id == "99999"
        return {"id": "99999", "roomName": "Studio 1"}

    import app.api.booking as booking_module

    monkeypatch.setattr(booking_module.crm_client, "get_beds24_booking", fake_get_beds24_booking)

    headers = {"Authorization": f"Bearer {make_quotation_token(tenant_id=None, booking_id=None)}"}
    response = client.get("/api/booking/99999", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"id": "99999", "roomName": "Studio 1"}
