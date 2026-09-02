import base64

from tests.conftest import ADMIN_USER


def _auth_headers_for(tenant_id=1, booking_id="12345"):
    from app.core.quotation_token import create_quotation_token

    token = create_quotation_token(tenant_id=tenant_id, booking_id=booking_id, issued_by_user_id=ADMIN_USER.id)
    return {"Authorization": f"Bearer {token}"}


def test_next_number_counts_existing_quotations(client, monkeypatch):
    import app.api.quotation as quotation_module

    async def fake_token():
        return "graph-token"

    async def fake_list(access_token, folder):
        return [
            "Quotation_12345_001 - Studio 1 - John - (a~b).pdf",
            "Quotation_12345_002 - Studio 1 - John - (a~b).pdf",
            "notes.txt",
        ]

    monkeypatch.setattr(quotation_module.onedrive_service, "get_graph_access_token", fake_token)
    monkeypatch.setattr(quotation_module.onedrive_service, "list_child_names", fake_list)

    response = client.post(
        "/api/quotation/onedrive/next-number",
        json={"booking_id": "12345", "first_name": "John", "last_name": "Doe", "year": 2026},
        headers=_auth_headers_for(),
    )
    assert response.status_code == 200
    assert response.json()["next_number"] == 3


def test_upload_decodes_and_calls_graph(client, monkeypatch):
    import app.api.quotation as quotation_module

    captured = {}

    async def fake_token():
        return "graph-token"

    async def fake_upload(access_token, folder, filename, content):
        captured["folder"] = folder
        captured["filename"] = filename
        captured["content"] = content
        return {"name": filename, "web_url": "https://onedrive.example/x.pdf", "id": "1"}

    monkeypatch.setattr(quotation_module.onedrive_service, "get_graph_access_token", fake_token)
    monkeypatch.setattr(quotation_module.onedrive_service, "upload_pdf", fake_upload)

    response = client.post(
        "/api/quotation/onedrive/upload",
        json={
            "booking_id": "12345",
            "first_name": "John",
            "last_name": "Doe",
            "year": 2026,
            "filename": "Quotation_12345_003.pdf",
            "content_base64": base64.b64encode(b"%PDF-1.4 test").decode("ascii"),
        },
        headers=_auth_headers_for(),
    )
    assert response.status_code == 200
    assert response.json()["web_url"] == "https://onedrive.example/x.pdf"
    assert captured["content"] == b"%PDF-1.4 test"
    assert captured["folder"].endswith("/2026/12345_John_Doe")


def test_upload_rejects_bad_base64(client, monkeypatch):
    import app.api.quotation as quotation_module

    async def fake_token():
        return "graph-token"

    monkeypatch.setattr(quotation_module.onedrive_service, "get_graph_access_token", fake_token)

    response = client.post(
        "/api/quotation/onedrive/upload",
        json={"booking_id": "1", "year": 2026, "filename": "x.pdf", "content_base64": "!!!not base64!!!"},
        headers=_auth_headers_for(),
    )
    assert response.status_code == 400


def test_onedrive_endpoints_require_token(client):
    assert client.post("/api/quotation/onedrive/next-number", json={"booking_id": "1", "year": 2026}).status_code == 401
