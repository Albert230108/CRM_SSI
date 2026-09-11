"""tenant_files_storage: local read-only access to the mounted TENANT_FILES_ROOT tree, backing
both the CRM dashboard's Files tile (app.api.tenant_files) and the Quotation Manager's
cross-tenant search (app.api.quotation's /quotation/tenant-files/* routes)."""

import pytest

from app.services import tenant_files_storage


@pytest.fixture()
def tenant_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TENANT_FILES_ROOT", str(tmp_path))
    return tmp_path


def _write(root, year, folder, filename, content=b"%PDF-1.4 fake"):
    d = root / str(year) / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(content)
    return d / filename


def test_root_not_configured_raises_503(monkeypatch):
    monkeypatch.delenv("TENANT_FILES_ROOT", raising=False)
    with pytest.raises(Exception) as exc_info:
        tenant_files_storage.list_tenant_folder(booking_id="1", first_name="A", last_name="B", check_in="2026-01-01")
    assert exc_info.value.status_code == 503


def test_list_tenant_folder_returns_items(tenant_root):
    _write(tenant_root, 2026, "12345_John_Doe", "Quotation_12345_001 - Studio 1 - John Doe - (a~b).pdf")

    result = tenant_files_storage.list_tenant_folder(
        booking_id="12345", first_name="John", last_name="Doe", check_in="2026-07-01"
    )
    assert result["folder_path"] == "2026/12345_John_Doe"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item.kind == "file"
    assert item.relative_path == "2026/12345_John_Doe/Quotation_12345_001 - Studio 1 - John Doe - (a~b).pdf"


def test_list_tenant_folder_missing_folder_returns_empty(tenant_root):
    result = tenant_files_storage.list_tenant_folder(
        booking_id="99999", first_name="Nobody", last_name="Here", check_in="2026-07-01"
    )
    assert result["items"] == []


def test_list_tenant_folder_requires_booking_id(tenant_root):
    with pytest.raises(Exception) as exc_info:
        tenant_files_storage.list_tenant_folder(booking_id="", first_name="A", last_name="B", check_in=None)
    assert exc_info.value.status_code == 400


def test_resolve_download_path_reads_the_file(tenant_root):
    path = _write(tenant_root, 2026, "12345_John_Doe", "Quotation_12345_001.pdf", content=b"%PDF-hello")
    resolved = tenant_files_storage.resolve_download_path("2026/12345_John_Doe/Quotation_12345_001.pdf")
    assert resolved == path.resolve()
    assert resolved.read_bytes() == b"%PDF-hello"


def test_resolve_download_path_rejects_traversal(tenant_root):
    (tenant_root.parent / "secret.txt").write_text("nope")
    with pytest.raises(Exception) as exc_info:
        tenant_files_storage.resolve_download_path("../secret.txt")
    assert exc_info.value.status_code == 404


def test_resolve_download_path_rejects_missing_file(tenant_root):
    with pytest.raises(Exception) as exc_info:
        tenant_files_storage.resolve_download_path("2026/does-not-exist.pdf")
    assert exc_info.value.status_code == 404


def test_search_filters_by_booking_id_year_tenant_name_room_and_text(tenant_root):
    _write(tenant_root, 2026, "12345_John_Doe", "Quotation_12345_001 - Studio 1 - John Doe - (a~b).pdf")
    _write(tenant_root, 2026, "67890_Jane_Smith", "Quotation_67890_001 - Loft 2 - Jane Smith - (a~b).pdf")
    _write(tenant_root, 2025, "11111_Old_Guest", "Quotation_11111_001 - Studio 1 - Old Guest - (a~b).pdf")

    all_results = tenant_files_storage.search_tenant_files()
    assert len(all_results) == 3

    by_booking = tenant_files_storage.search_tenant_files(booking_id="12345")
    assert [r.name for r in by_booking] == ["Quotation_12345_001 - Studio 1 - John Doe - (a~b).pdf"]

    by_year = tenant_files_storage.search_tenant_files(year=2025)
    assert len(by_year) == 1 and "11111" in by_year[0].relative_path

    by_tenant_name = tenant_files_storage.search_tenant_files(tenant_name="jane")
    assert len(by_tenant_name) == 1 and "Jane_Smith" in by_tenant_name[0].relative_path

    by_room = tenant_files_storage.search_tenant_files(room="loft 2")
    assert len(by_room) == 1 and "67890" in by_room[0].relative_path

    by_q = tenant_files_storage.search_tenant_files(q="old guest")
    assert len(by_q) == 1 and "11111" in by_q[0].relative_path


def test_search_missing_root_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("TENANT_FILES_ROOT", str(tmp_path / "does-not-exist"))
    assert tenant_files_storage.search_tenant_files() == []


def test_search_respects_limit(tenant_root):
    for i in range(5):
        _write(tenant_root, 2026, f"{i}_Guest_{i}", f"Quotation_{i}_001.pdf")
    assert len(tenant_files_storage.search_tenant_files(limit=2)) == 2
