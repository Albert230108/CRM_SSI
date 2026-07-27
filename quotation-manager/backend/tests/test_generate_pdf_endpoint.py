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
