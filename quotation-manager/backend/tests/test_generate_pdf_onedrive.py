import base64


def test_generate_pdf_uploads_to_onedrive_when_configured(client, auth_headers, monkeypatch):
    captured = {}

    async def fake_next_number(token, payload):
        captured["number_payload"] = payload
        return {"next_number": 3, "folder_path": "/01. Rentals/02. Short-Stay Inn/Tenants/2026/12345_John_Doe"}

    async def fake_upload(token, payload):
        captured["upload_payload"] = payload
        return {"name": payload["filename"], "web_url": "https://onedrive.example/Quotation.pdf", "folder_path": "/f"}

    import app.api.quotation as quotation_module

    monkeypatch.setattr(quotation_module.crm_client, "onedrive_next_number", fake_next_number)
    monkeypatch.setattr(quotation_module.crm_client, "onedrive_upload", fake_upload)

    response = client.post(
        "/api/quotation/generate-pdf",
        json={
            "booking_id": "12345",
            "first_name": "John",
            "last_name": "Doe",
            "room_name": "Studio 1",
            "property_name": "Central-Day Inn",
            "check_in": "2026-07-01",
            "check_out": "2026-07-08",
            "security_deposit": 400.0,
            "invoice_items": [{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9}],
            "quotation_date": "01 Jan 2026",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["location"] == "onedrive"
    assert body["quotation_number"] == 3
    assert body["web_url"] == "https://onedrive.example/Quotation.pdf"

    # Year derived from check-in; number came from the CRM listing.
    assert captured["number_payload"]["year"] == 2026
    assert captured["upload_payload"]["filename"].startswith("Quotation_12345_003 - Studio 1 - John Doe")
    decoded = base64.b64decode(captured["upload_payload"]["content_base64"])
    assert decoded[:4] == b"%PDF"
