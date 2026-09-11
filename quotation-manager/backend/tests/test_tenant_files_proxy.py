"""The Quotation Manager's Files page proxies straight to the CRM backend, which owns the
mounted TENANT_FILES_ROOT tree - these tests only cover the proxy layer (crm_client is mocked)."""


def test_search_forwards_filters_and_drops_empty_ones(client, auth_headers, monkeypatch):
    import app.api.quotation as quotation_module

    captured = {}

    async def fake_search(token, params):
        captured["token"] = token
        captured["params"] = params
        return {"items": [{"name": "Quotation_12345_001.pdf", "kind": "file", "size": 1024, "relative_path": "2026/12345_John_Doe/Quotation_12345_001.pdf"}]}

    monkeypatch.setattr(quotation_module.crm_client, "search_tenant_files", fake_search)

    response = client.get("/api/quotation/tenant-files/search", params={"tenant_name": "john"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Quotation_12345_001.pdf"
    assert captured["params"]["tenant_name"] == "john"
    assert captured["params"]["booking_id"] is None


def test_search_requires_token(client):
    assert client.get("/api/quotation/tenant-files/search").status_code == 401


def test_download_streams_bytes_from_crm(client, auth_headers, monkeypatch):
    import app.api.quotation as quotation_module

    async def fake_download(relative_path, token):
        assert relative_path == "2026/12345_John_Doe/Quotation_12345_001.pdf"
        return b"%PDF-hello", "application/pdf"

    monkeypatch.setattr(quotation_module.crm_client, "download_tenant_file", fake_download)

    response = client.get(
        "/api/quotation/tenant-files/download",
        params={"path": "2026/12345_John_Doe/Quotation_12345_001.pdf"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.content == b"%PDF-hello"
    assert "Quotation_12345_001.pdf" in response.headers["content-disposition"]


def test_download_requires_token(client):
    assert client.get("/api/quotation/tenant-files/download", params={"path": "x"}).status_code == 401
