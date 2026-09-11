import base64

import pytest

from app.services import tenant_files


@pytest.fixture()
def tenant_root(tmp_path, monkeypatch):
    monkeypatch.setattr(tenant_files, "TENANT_FILES_ROOT_PATH", tmp_path)
    return tmp_path


def test_generate_pdf_endpoint_writes_file_to_tenant_folder(client, auth_headers, tenant_root):
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
            "invoice_items": [
                {"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9},
            ],
            "quotation_date": "01 Jan 2026",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quotation_number"] == 1

    generated_path = tenant_root / "2026" / "12345_John_Doe"
    pdfs = list(generated_path.glob("Quotation_12345_*.pdf"))
    assert len(pdfs) == 1


def test_generate_pdf_include_content_returns_base64(client, auth_headers, tenant_root):
    """The sales-manager agent asks for the PDF bytes back so it can attach the quotation."""
    payload = {
        "booking_id": "12345",
        "first_name": "John",
        "last_name": "Doe",
        "room_name": "Studio 1",
        "property_name": "Central-Day Inn",
        "check_in": "2026-07-01",
        "check_out": "2026-07-08",
        "security_deposit": 400.0,
        "invoice_items": [
            {"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9},
        ],
        "quotation_date": "01 Jan 2026",
        "include_content": True,
    }
    response = client.post("/api/quotation/generate-pdf", json=payload, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["content_base64"]
    decoded = base64.b64decode(body["content_base64"])
    assert decoded[:5] == b"%PDF-"


def test_generate_pdf_omits_content_by_default(client, auth_headers, tenant_root):
    payload = {
        "booking_id": "12345",
        "first_name": "John",
        "last_name": "Doe",
        "room_name": "Studio 1",
        "check_in": "2026-07-01",
        "check_out": "2026-07-08",
        "invoice_items": [{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9}],
        "quotation_date": "01 Jan 2026",
    }
    response = client.post("/api/quotation/generate-pdf", json=payload, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["content_base64"] is None


def test_vat_split_endpoint(client, auth_headers):
    response = client.post(
        "/api/quotation/vat-split",
        json={"start_date": "2025-12-28", "end_date": "2026-01-05", "price_per_night": 100.0},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["vat"] == 9
    assert body[1]["vat"] == 21


# --- delivery="download": render only, nothing is ever written to disk ---


def test_generate_pdf_download_returns_base64_and_writes_nothing(client, auth_headers, tenant_root):
    payload = {
        "booking_id": "12345",
        "first_name": "John",
        "last_name": "Doe",
        "room_name": "Studio 1",
        "property_name": "Central-Day Inn",
        "check_in": "2026-07-01",
        "check_out": "2026-07-08",
        "security_deposit": 400.0,
        "invoice_items": [
            {"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9},
        ],
        "quotation_date": "01 Jan 2026",
        "delivery": "download",
    }
    response = client.post("/api/quotation/generate-pdf", json=payload, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["location"] == "download"
    assert body["quotation_number"] == 1
    assert body["content_base64"]
    decoded = base64.b64decode(body["content_base64"])
    assert decoded[:5] == b"%PDF-"

    # Nothing should have been written to the tenant folder at all.
    assert not (tenant_root / "2026").exists()


def test_generate_pdf_download_draft_skips_onedrive_lookup_and_numbers_from_one(client, auth_headers, tenant_root):
    payload = {
        "booking_id": "Draft",
        "first_name": "Jane",
        "last_name": "Doe",
        "room_name": "Studio 1",
        "property_name": "Central-Day Inn",
        "check_in": "2026-08-01",
        "check_out": "2026-08-08",
        "invoice_items": [{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9}],
        "quotation_date": "01 Jan 2026",
        "delivery": "download",
    }
    response = client.post("/api/quotation/generate-pdf", json=payload, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["quotation_number"] == 1
    assert body["location"] == "download"
    assert not (tenant_root / "2026").exists()


def test_generate_pdf_download_numbers_past_existing_local_files(client, auth_headers, tenant_root):
    # A download should still count what's already in the tenant folder (matching
    # the save flow's numbering) - it just never writes anything itself.
    existing_folder = tenant_root / "2026" / "12345_John_Doe"
    existing_folder.mkdir(parents=True)
    (existing_folder / "Quotation_12345_001 - x - y - (a~b).pdf").write_bytes(b"%PDF-fake")

    payload = {
        "booking_id": "12345",
        "first_name": "John",
        "last_name": "Doe",
        "room_name": "Studio 1",
        "check_in": "2026-07-01",
        "check_out": "2026-07-08",
        "invoice_items": [{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9}],
        "quotation_date": "01 Jan 2026",
        "delivery": "download",
    }
    response = client.post("/api/quotation/generate-pdf", json=payload, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["quotation_number"] == 2
    # Still only the one file that was already there - download wrote nothing.
    assert len(list(existing_folder.glob("*.pdf"))) == 1


def test_generate_pdf_save_flow_still_writes_by_default(client, auth_headers, tenant_root):
    # delivery defaults to "save" when omitted - unchanged prior behaviour.
    payload = {
        "booking_id": "99999",
        "first_name": "Jo",
        "last_name": "Doe",
        "room_name": "Studio 1",
        "check_in": "2026-07-01",
        "check_out": "2026-07-08",
        "invoice_items": [{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9}],
        "quotation_date": "01 Jan 2026",
    }
    response = client.post("/api/quotation/generate-pdf", json=payload, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["location"] == "local"
    generated_path = tenant_root / "2026" / "99999_Jo_Doe"
    assert len(list(generated_path.glob("Quotation_99999_*.pdf"))) == 1


def test_generate_pdf_endpoint_accepts_mixed_charge_and_payment_items(client, auth_headers, tenant_root):
    # Regression: generate-pdf already renders a real "Proposed payment schedule"
    # when payment rows are included - the prior emptiness was purely because the
    # frontend only ever sent charges. Confirms the backend needs no change there.
    payload = {
        "booking_id": "55555",
        "first_name": "Jo",
        "last_name": "Doe",
        "room_name": "Studio 1",
        "check_in": "2026-07-01",
        "check_out": "2026-07-08",
        "invoice_items": [
            {"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9},
            {"type": "payment", "description": "Installment 1", "qty": 1, "amount": 455.0, "vat_rate": 0, "status": "not paid"},
            {"type": "payment", "description": "Installment 2", "qty": 1, "amount": 100.0, "vat_rate": 0, "status": "12-Sep-2026"},
        ],
        "quotation_date": "01 Jan 2026",
        "include_content": True,
    }
    response = client.post("/api/quotation/generate-pdf", json=payload, headers=auth_headers)
    assert response.status_code == 200
    decoded = base64.b64decode(response.json()["content_base64"])
    assert decoded[:5] == b"%PDF-"


def test_generate_pdf_threads_room_id_to_pdf_service(client, auth_headers, tenant_root, monkeypatch):
    """C1 regression: room_id must reach create_invoice_pdf so STUDIO_LINK_MAPPING can render
    the clickable studio/room link. Before the fix room_id was never threaded (always None)."""
    from app.api import quotation as quotation_api

    captured = {}

    def fake_create_invoice_pdf(**kwargs):
        captured.update(kwargs)
        kwargs["output_path"].write_bytes(b"%PDF-1.4 fake")
        return kwargs["output_path"]

    monkeypatch.setattr(quotation_api.pdf_service, "create_invoice_pdf", fake_create_invoice_pdf)

    response = client.post(
        "/api/quotation/generate-pdf",
        json={
            "booking_id": "12345",
            "first_name": "John",
            "last_name": "Doe",
            "room_name": "Studio 1",
            "room_id": 262377,
            "property_name": "Central-Day Inn",
            "check_in": "2026-07-01",
            "check_out": "2026-07-08",
            "security_deposit": 400.0,
            "invoice_items": [{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9}],
            "quotation_date": "01-Jan-2026",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert captured.get("room_id") == 262377
