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
