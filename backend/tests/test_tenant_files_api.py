"""The CRM dashboard's server-folder Files tab: GET /api/tenant-files/tenant/{id} and
/api/tenant-files/download, guarded by ordinary CRM user auth (unlike the Quotation Manager's
own tenant-files routes under /api/quotation/tenant-files/*, covered in
test_quotation_tenant_files_endpoints.py)."""

import pytest

from app.models.tenant import Tenant


@pytest.fixture()
def tenant_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TENANT_FILES_ROOT", str(tmp_path))
    return tmp_path


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Files Tab Tenant", booking_id="B-files-1", first_name="Sam", last_name="Jones",
        check_in="2026-07-01", check_out="2026-07-08", room_name="Studio 1",
    )
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_list_tenant_files_returns_items(non_admin_client, db_session, tenant_root):
    tenant = _create_tenant(db_session)
    folder = tenant_root / "2026" / "B-files-1_Sam_Jones"
    folder.mkdir(parents=True)
    (folder / "Quotation_B-files-1_001 - Studio 1 - Sam Jones - (a~b).pdf").write_bytes(b"%PDF-1.4")

    response = non_admin_client.get(f"/api/tenant-files/tenant/{tenant.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["folder_path"] == "2026/B-files-1_Sam_Jones"
    assert len(body["items"]) == 1
    assert body["items"][0]["kind"] == "file"


def test_list_tenant_files_missing_folder_returns_empty_not_error(non_admin_client, db_session, tenant_root):
    tenant = _create_tenant(db_session, booking_id="B-files-2")
    response = non_admin_client.get(f"/api/tenant-files/tenant/{tenant.id}")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_tenant_files_404_for_missing_tenant(non_admin_client, tenant_root):
    response = non_admin_client.get("/api/tenant-files/tenant/999999")
    assert response.status_code == 404


def test_download_tenant_file_returns_bytes(non_admin_client, db_session, tenant_root):
    tenant = _create_tenant(db_session, booking_id="B-files-3")
    folder = tenant_root / "2026" / "B-files-3_Sam_Jones"
    folder.mkdir(parents=True)
    (folder / "Quotation_B-files-3_001.pdf").write_bytes(b"%PDF-hello")

    response = non_admin_client.get(
        "/api/tenant-files/download", params={"path": "2026/B-files-3_Sam_Jones/Quotation_B-files-3_001.pdf"}
    )
    assert response.status_code == 200
    assert response.content == b"%PDF-hello"
    assert "Quotation_B-files-3_001.pdf" in response.headers["content-disposition"]


def test_download_tenant_file_rejects_traversal(non_admin_client, tenant_root):
    response = non_admin_client.get("/api/tenant-files/download", params={"path": "../../etc/passwd"})
    assert response.status_code == 404


def test_tenant_files_routes_require_auth(client, tenant_root):
    # `client` (see conftest) carries no Authorization header.
    assert client.get("/api/tenant-files/tenant/1").status_code == 401
    assert client.get("/api/tenant-files/download", params={"path": "x"}).status_code == 401


def test_upload_tenant_file_writes_into_booking_folder(non_admin_client, db_session, tenant_root):
    tenant = _create_tenant(db_session, booking_id="B-files-up")
    response = non_admin_client.post(
        f"/api/tenant-files/tenant/{tenant.id}/upload",
        files={"file": ("contract.pdf", b"%PDF-upload", "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "contract.pdf"
    assert body["relative_path"] == "2026/B-files-up_Sam_Jones/contract.pdf"
    assert (tenant_root / "2026" / "B-files-up_Sam_Jones" / "contract.pdf").read_bytes() == b"%PDF-upload"


def test_upload_tenant_file_dedupes_colliding_names(non_admin_client, db_session, tenant_root):
    tenant = _create_tenant(db_session, booking_id="B-files-dup")
    for _ in range(2):
        response = non_admin_client.post(
            f"/api/tenant-files/tenant/{tenant.id}/upload",
            files={"file": ("note.txt", b"data", "text/plain")},
        )
        assert response.status_code == 201
    names = sorted(p.name for p in (tenant_root / "2026" / "B-files-dup_Sam_Jones").iterdir())
    assert names == ["note (1).txt", "note.txt"]


def test_upload_tenant_file_404_for_missing_tenant(non_admin_client, tenant_root):
    response = non_admin_client.post(
        "/api/tenant-files/tenant/999999/upload",
        files={"file": ("x.txt", b"data", "text/plain")},
    )
    assert response.status_code == 404


def test_upload_tenant_file_requires_auth(client, tenant_root):
    response = client.post(
        "/api/tenant-files/tenant/1/upload", files={"file": ("x.txt", b"data", "text/plain")}
    )
    assert response.status_code == 401
