"""The Quotation Manager's cross-tenant Files page: GET /api/quotation/tenant-files/search and
/api/quotation/tenant-files/download, guarded by the scoped quotation token (unlike the CRM
dashboard's own tenant-files routes in test_tenant_files_api.py, which use ordinary user auth)."""

import pytest

from tests.conftest import ADMIN_USER


@pytest.fixture()
def tenant_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TENANT_FILES_ROOT", str(tmp_path))
    return tmp_path


def _auth_headers_for(tenant_id=None, booking_id=None):
    from app.core.quotation_token import create_quotation_token

    token = create_quotation_token(tenant_id=tenant_id, booking_id=booking_id, issued_by_user_id=ADMIN_USER.id)
    return {"Authorization": f"Bearer {token}"}


def _write(root, year, folder, filename, content=b"%PDF-1.4 fake"):
    d = root / str(year) / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(content)
    return d / filename


def test_search_is_not_pinned_to_the_tokens_own_tenant(client, tenant_root):
    _write(tenant_root, 2026, "12345_John_Doe", "Quotation_12345_001 - Studio 1 - John Doe - (a~b).pdf")
    _write(tenant_root, 2026, "67890_Jane_Smith", "Quotation_67890_001 - Loft 2 - Jane Smith - (a~b).pdf")

    # Token minted for a different tenant/booking entirely - ad-hoc cross-tenant search is the
    # explicit point of this page, same rationale as the existing booking-lookup endpoints.
    response = client.get("/api/quotation/tenant-files/search", headers=_auth_headers_for(tenant_id=1, booking_id="99999"))
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["items"]}
    assert names == {
        "Quotation_12345_001 - Studio 1 - John Doe - (a~b).pdf",
        "Quotation_67890_001 - Loft 2 - Jane Smith - (a~b).pdf",
    }


def test_search_filters_by_query_params(client, tenant_root):
    _write(tenant_root, 2026, "12345_John_Doe", "Quotation_12345_001 - Studio 1 - John Doe - (a~b).pdf")
    _write(tenant_root, 2026, "67890_Jane_Smith", "Quotation_67890_001 - Loft 2 - Jane Smith - (a~b).pdf")

    response = client.get(
        "/api/quotation/tenant-files/search",
        params={"tenant_name": "jane"},
        headers=_auth_headers_for(),
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert "Jane_Smith" in items[0]["relative_path"]


def test_search_requires_token(client, tenant_root):
    assert client.get("/api/quotation/tenant-files/search").status_code == 401


def test_download_streams_the_file(client, tenant_root):
    _write(tenant_root, 2026, "12345_John_Doe", "Quotation_12345_001.pdf", content=b"%PDF-hello")

    response = client.get(
        "/api/quotation/tenant-files/download",
        params={"path": "2026/12345_John_Doe/Quotation_12345_001.pdf"},
        headers=_auth_headers_for(),
    )
    assert response.status_code == 200
    assert response.content == b"%PDF-hello"


def test_download_rejects_traversal(client, tenant_root):
    response = client.get(
        "/api/quotation/tenant-files/download",
        params={"path": "../../etc/passwd"},
        headers=_auth_headers_for(),
    )
    assert response.status_code == 404


def test_download_requires_token(client, tenant_root):
    assert client.get("/api/quotation/tenant-files/download", params={"path": "x"}).status_code == 401
