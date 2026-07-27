def test_send_to_beds24_forwards_payload_and_bearer_token(client, auth_headers, monkeypatch):
    captured = {}

    async def fake_send_invoice_items_to_beds24(booking_id, token, payload):
        captured["booking_id"] = booking_id
        captured["token"] = token
        captured["payload"] = payload
        return {"tenant_id": 1, "charges": [], "payments": []}

    import app.api.quotation as quotation_module

    monkeypatch.setattr(quotation_module.crm_client, "send_invoice_items_to_beds24", fake_send_invoice_items_to_beds24)

    response = client.post(
        "/api/quotation/12345/send-to-beds24",
        json={
            "all_original_invoice_item_ids": ["old-1"],
            "invoice_items": [{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"tenant_id": 1, "charges": [], "payments": []}
    assert captured["booking_id"] == "12345"
    assert captured["payload"]["all_original_invoice_item_ids"] == ["old-1"]
    assert captured["payload"]["invoice_items"][0]["description"] == "Rent"


def test_send_to_beds24_requires_token(client):
    response = client.post(
        "/api/quotation/12345/send-to-beds24",
        json={"all_original_invoice_item_ids": [], "invoice_items": []},
    )
    assert response.status_code == 401
