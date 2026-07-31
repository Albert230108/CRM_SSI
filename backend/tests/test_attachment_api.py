import pytest

from app.models.communication_attachment import CommunicationAttachment
from app.models.tenant import Tenant


@pytest.fixture(autouse=True)
def attachments_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_ROOT", str(tmp_path))
    yield tmp_path


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_upload_returns_stored_metadata(non_admin_client, db_session, attachments_root):
    tenant = create_tenant(db_session)

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/attachments",
        files=[("files", ("invoice.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body) == 1
    assert body[0]["filename"] == "invoice.pdf"
    assert body[0]["mime_type"] == "application/pdf"
    assert body[0]["size_bytes"] == len(b"%PDF-1.4 fake")
    assert body[0]["origin"] == "upload"

    record = db_session.query(CommunicationAttachment).filter_by(id=body[0]["id"]).one()
    assert (attachments_root / record.storage_key).read_bytes() == b"%PDF-1.4 fake"


def test_upload_rejects_oversize_file(non_admin_client, db_session, monkeypatch):
    monkeypatch.setenv("ATTACHMENT_MAX_FILE_BYTES", "16")
    tenant = create_tenant(db_session)

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/attachments",
        files=[("files", ("big.bin", b"x" * 17, "application/octet-stream"))],
    )

    assert response.status_code == 413


def test_upload_rejects_when_request_total_exceeds_cap(non_admin_client, db_session, monkeypatch):
    monkeypatch.setenv("ATTACHMENT_MAX_FILE_BYTES", "100")
    monkeypatch.setenv("ATTACHMENT_MAX_MESSAGE_BYTES", "10")
    tenant = create_tenant(db_session)

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/attachments",
        files=[
            ("files", ("a.bin", b"x" * 6, "application/octet-stream")),
            ("files", ("b.bin", b"y" * 6, "application/octet-stream")),
        ],
    )

    assert response.status_code == 413


def test_reupload_of_identical_content_reuses_the_same_blob(non_admin_client, db_session):
    tenant = create_tenant(db_session)

    first = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/attachments",
        files=[("files", ("a.txt", b"same bytes", "text/plain"))],
    )
    second = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/attachments",
        files=[("files", ("renamed.txt", b"same bytes", "text/plain"))],
    )

    assert first.json()[0]["id"] == second.json()[0]["id"]


def test_download_sets_attachment_disposition_and_nosniff(non_admin_client, db_session):
    tenant = create_tenant(db_session)
    uploaded = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/attachments",
        files=[("files", ("report.txt", b"payload", "text/plain"))],
    ).json()[0]

    response = non_admin_client.get(
        f"/api/communications/tenants/{tenant.id}/attachments/{uploaded['id']}/download"
    )

    assert response.status_code == 200
    assert response.content == b"payload"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_download_of_another_tenants_attachment_is_404(non_admin_client, db_session):
    owner = create_tenant(db_session, name="Owner", booking_id="B-owner")
    other = create_tenant(db_session, name="Other", booking_id="B-other")
    uploaded = non_admin_client.post(
        f"/api/communications/tenants/{owner.id}/attachments",
        files=[("files", ("secret.txt", b"confidential", "text/plain"))],
    ).json()[0]

    response = non_admin_client.get(
        f"/api/communications/tenants/{other.id}/attachments/{uploaded['id']}/download"
    )

    assert response.status_code == 404


def test_history_listing_is_scoped_to_the_tenant(non_admin_client, db_session):
    owner = create_tenant(db_session, name="Owner", booking_id="B-owner")
    other = create_tenant(db_session, name="Other", booking_id="B-other")
    non_admin_client.post(
        f"/api/communications/tenants/{owner.id}/attachments",
        files=[("files", ("mine.txt", b"mine", "text/plain"))],
    )
    non_admin_client.post(
        f"/api/communications/tenants/{other.id}/attachments",
        files=[("files", ("theirs.txt", b"theirs", "text/plain"))],
    )

    listing = non_admin_client.get(f"/api/communications/tenants/{owner.id}/attachments").json()

    assert [item["filename"] for item in listing] == ["mine.txt"]


def test_history_listing_filters_by_filename_query(non_admin_client, db_session):
    tenant = create_tenant(db_session)
    for name in ("contract.pdf", "photo.png"):
        non_admin_client.post(
            f"/api/communications/tenants/{tenant.id}/attachments",
            files=[("files", (name, name.encode(), "application/octet-stream"))],
        )

    listing = non_admin_client.get(
        f"/api/communications/tenants/{tenant.id}/attachments", params={"q": "contract"}
    ).json()

    assert [item["filename"] for item in listing] == ["contract.pdf"]


def test_upload_for_unknown_tenant_is_404(non_admin_client, db_session):
    response = non_admin_client.post(
        "/api/communications/tenants/999999/attachments",
        files=[("files", ("a.txt", b"data", "text/plain"))],
    )

    assert response.status_code == 404
