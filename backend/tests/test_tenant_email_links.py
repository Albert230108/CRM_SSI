import time
from unittest.mock import AsyncMock, patch

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from app.services.background_jobs import get_job

REGULAR_USER = User(id=2, email="agent@example.com", password_hash="x", is_active=True, is_admin=False)

NO_OP_GMAIL_SYNC_RESULT = {"accounts_checked": 0, "accounts_failed": 0, "conversations_matched": 0}


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def wait_for_job(job_id, timeout=2.0):
    deadline = time.monotonic() + timeout
    job = get_job(job_id)
    while job and job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        job = get_job(job_id)
    return job


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def mock_gmail_sync():
    with patch("app.api.tenant_email_links.sync_email_across_gmail_accounts", return_value=NO_OP_GMAIL_SYNC_RESULT) as mocked:
        yield mocked


def test_create_email_link_happy_path(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-email-1")
    fake_info_item = {"id": "999", "code": "CRM_EMAIL", "text": "guest@example.com"}

    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value=fake_info_item)) as mocked_add:
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert response.status_code == 200
    body = response.json()
    link = body["link"]
    assert link["email"] == "guest@example.com"
    assert link["tenant_id"] == tenant.id
    assert link["is_active"] is True
    assert link["beds24_sync_status"] == "synced"
    assert link["linked_by_user_id"] == REGULAR_USER.id
    assert body["gmail_sync_job_id"]
    mocked_add.assert_awaited_once_with("B-email-1", "CRM_EMAIL", "guest@example.com")


def test_create_email_link_triggers_gmail_sync_job(user_client, db_session, mock_gmail_sync):
    tenant = create_tenant(db_session, booking_id="B-email-gmail-sync")
    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "1"})):
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert response.status_code == 200
    job_id = response.json()["gmail_sync_job_id"]
    assert job_id

    job = wait_for_job(job_id)
    assert job is not None
    assert job["status"] == "done"
    assert job["result"] == NO_OP_GMAIL_SYNC_RESULT
    mock_gmail_sync.assert_called_once_with("guest@example.com")


def test_create_email_link_beds24_failure_keeps_crm_link(user_client, db_session):
    from fastapi import HTTPException

    tenant = create_tenant(db_session, booking_id="B-email-fail")
    with patch(
        "app.api.tenant_email_links.add_booking_info_item",
        new=AsyncMock(side_effect=HTTPException(status_code=502, detail="Beds24 upstream error")),
    ):
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert response.status_code == 200
    link = response.json()["link"]
    assert link["beds24_sync_status"] == "failed"
    assert link["is_active"] is True

    links = user_client.get(f"/api/tenants/{tenant.id}/email-links").json()
    assert len(links) == 1
    assert links[0]["beds24_sync_status"] == "failed"


def test_create_email_link_conflict_requires_confirmation(user_client, db_session):
    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="B-conflict-a")
    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="B-conflict-b")

    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "1"})):
        first = user_client.post(f"/api/tenants/{tenant_a.id}/email-links", json={"email": "shared@example.com"})
    assert first.status_code == 200

    without_confirm = user_client.post(f"/api/tenants/{tenant_b.id}/email-links", json={"email": "shared@example.com"})
    assert without_confirm.status_code == 409
    detail = without_confirm.json()["detail"]
    assert detail["conflicting_tenant_id"] == tenant_a.id
    assert detail["conflicting_tenant_name"] == "Tenant A"

    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "2"})):
        with_confirm = user_client.post(
            f"/api/tenants/{tenant_b.id}/email-links",
            json={"email": "shared@example.com", "confirm_conflict": True},
        )
    assert with_confirm.status_code == 200
    assert with_confirm.json()["link"]["tenant_id"] == tenant_b.id

    a_links = user_client.get(f"/api/tenants/{tenant_a.id}/email-links").json()
    b_links = user_client.get(f"/api/tenants/{tenant_b.id}/email-links").json()
    assert len(a_links) == 1
    assert len(b_links) == 1


def test_unlink_email_link_removes_beds24_info_item(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-unlink-email")
    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "555"})):
        created = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"}).json()["link"]

    with patch("app.api.tenant_email_links.delete_booking_info_item", new=AsyncMock(return_value=None)) as mocked_delete:
        delete_response = user_client.delete(f"/api/tenants/{tenant.id}/email-links/{created['id']}")

    assert delete_response.status_code == 200
    assert delete_response.json()["is_active"] is False
    mocked_delete.assert_awaited_once_with("B-unlink-email", "555")

    active_links = user_client.get(f"/api/tenants/{tenant.id}/email-links").json()
    assert active_links == []


def test_relink_same_email_same_tenant_is_idempotent(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-idempotent")
    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "1"})) as mocked_add:
        first = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})
        second = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["link"]["id"] == second.json()["link"]["id"]
    assert second.json()["gmail_sync_job_id"] is None
    mocked_add.assert_awaited_once()

    links = user_client.get(f"/api/tenants/{tenant.id}/email-links").json()
    assert len(links) == 1


def test_permissions_require_authentication(client_without_webhook_secret, db_session):
    from app.core.dependencies import get_current_user as real_get_current_user

    app.dependency_overrides.pop(real_get_current_user, None)
    tenant = create_tenant(db_session, booking_id="B-perm-email")
    response = client_without_webhook_secret.post(
        f"/api/tenants/{tenant.id}/email-links",
        json={"email": "guest@example.com"},
    )
    assert response.status_code == 401
