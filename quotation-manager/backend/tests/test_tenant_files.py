import pytest

from app.services import tenant_files


@pytest.fixture()
def tenant_root(tmp_path, monkeypatch):
    monkeypatch.setattr(tenant_files, "TENANT_FILES_ROOT_PATH", tmp_path)
    return tmp_path


def test_create_booking_folder_uses_arrival_year(tenant_root):
    folder = tenant_files.create_booking_folder("12345", "John", "Doe", "2026-07-01")
    assert folder.exists()
    assert folder.parent.name == "2026"
    assert folder.name == "12345_John_Doe"


def test_create_booking_folder_rejects_bad_date(tenant_root):
    with pytest.raises(tenant_files.TenantFolderError):
        tenant_files.create_booking_folder("12345", "John", "Doe", "not-a-date")


def test_next_quotation_output_path_increments_across_existing_files(tenant_root):
    folder = tenant_root / "2026" / "12345_John_Doe"
    folder.mkdir(parents=True)

    first = tenant_files.next_quotation_output_path(folder, "12345", "Studio 1", "John Doe", "2026-07-01", "2026-07-08")
    assert first.quotation_number == 1
    first.path.write_bytes(b"fake pdf")

    second = tenant_files.next_quotation_output_path(folder, "12345", "Studio 1", "John Doe", "2026-07-01", "2026-07-08")
    assert second.quotation_number == 2
    assert second.path != first.path


def test_next_quotation_output_path_formats_dates_and_filename(tenant_root):
    folder = tenant_root / "2026" / "12345_John_Doe"
    folder.mkdir(parents=True)

    result = tenant_files.next_quotation_output_path(folder, "12345", "Studio 1", "John Doe", "2026-07-01", "2026-07-08")
    assert "Quotation_12345_001" in result.path.name
    assert "01 Jul 2026" in result.path.name
    assert "08 Jul 2026" in result.path.name
