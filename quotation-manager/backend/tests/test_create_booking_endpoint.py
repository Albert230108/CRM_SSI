def test_create_booking_forwards_payload_and_bearer_token(client, auth_headers, monkeypatch):
    captured = {}

    async def fake_create_booking(token, payload):
        captured["token"] = token
        captured["payload"] = payload
        return {"booking_id": "99999", "tenant_id": 7, "charges": [], "payments": []}

    import app.api.quotation as quotation_module

    monkeypatch.setattr(quotation_module.crm_client, "create_booking", fake_create_booking)

    response = client.post(
        "/api/quotation/create-booking",
        json={
            "room_id": 262377,
            "arrival": "2025-06-01",
            "departure": "2025-06-08",
            "status": "inquiry",
            "first_name": "Jane",
            "last_name": "Doe",
            "num_adults": 2,
            "invoice_items": [{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["booking_id"] == "99999"
    assert captured["payload"]["room_id"] == 262377
    assert captured["payload"]["first_name"] == "Jane"
    assert captured["payload"]["invoice_items"][0]["description"] == "Rent"


def test_create_booking_requires_token(client):
    response = client.post(
        "/api/quotation/create-booking",
        json={"room_id": 1, "arrival": "2025-06-01", "departure": "2025-06-08", "first_name": "Jane"},
    )
    assert response.status_code == 401
