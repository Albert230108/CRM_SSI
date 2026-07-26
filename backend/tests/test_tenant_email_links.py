from unittest.mock import AsyncMock, patch

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User

REGULAR_USER = User(id=2, email="agent@example.com", password_hash="x", is_active=True, is_admin=False)


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_create_email_link_happy_path(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-email-1")
    fake_info_item = {"id": "999", "code": "CRM_EMAIL", "text": "guest@example.com"}

    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value=fake_info_item)) as mocked_add:
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "guest@example.com"
    assert body["tenant_id"] == tenant.id
    assert body["is_active"] is True
    assert body["beds24_sync_status"] == "synced"
    assert body["linked_by_user_id"] == REGULAR_USER.id
    mocked_add.assert_awaited_once_with("B-email-1", "CRM_EMAIL", "guest@example.com")


def test_create_email_link_beds24_failure_keeps_crm_link(user_client, db_session):
    from fastapi import HTTPException

    tenant = create_tenant(db_session, booking_id="B-email-fail")
    with patch(
        "app.api.tenant_email_links.add_booking_info_item",
        new=AsyncMock(side_effect=HTTPException(status_code=502, detail="Beds24 upstream error")),
    ):
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["beds24_sync_status"] == "failed"
    assert body["is_active"] is True

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
    assert with_confirm.json()["tenant_id"] == tenant_b.id

    a_links = user_client.get(f"/api/tenants/{tenant_a.id}/email-links").json()
    b_links = user_client.get(f"/api/tenants/{tenant_b.id}/email-links").json()
    assert len(a_links) == 1
    assert len(b_links) == 1


def test_unlink_email_link_removes_beds24_info_item(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-unlink-email")
    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "555"})):
        created = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"}).json()

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
    assert first.json()["id"] == second.json()["id"]
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
