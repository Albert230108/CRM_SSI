from unittest.mock import AsyncMock, patch

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User
from app.services.tenant_channel_resolver import resolve_tenant_for_inbound_channel
from app.webhooks.whatsapp import _build_backfill_identity_entries

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


def test_get_whatsapp_accounts(user_client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_SERVICE_ACCOUNTS", '[{"external_account_id": "edi-crm-whatsapp", "provider": "whatsapp-service", "label": "EDI CRM WhatsApp"}]')
    response = user_client.get("/api/whatsapp/accounts")
    assert response.status_code == 200
    body = response.json()
    assert body == [{"external_account_id": "edi-crm-whatsapp", "provider": "whatsapp-service", "label": "EDI CRM WhatsApp"}]


def test_get_whatsapp_account_chats_search_by_chat_id(user_client, db_session):
    fake_chats = [
        {"chat_id": "326472368@lid", "chat_name": "Alberto", "last_message_timestamp": None, "last_message_preview": "Hi there"},
        {"chat_id": "111222333@c.us", "chat_name": "Someone Else", "last_message_timestamp": None, "last_message_preview": None},
    ]
    with patch("app.api.whatsapp_thread_links.fetch_whatsapp_chats", new=AsyncMock(return_value=fake_chats)):
        response = user_client.get("/api/whatsapp/accounts/edi-crm-whatsapp/chats", params={"search": "326472368"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["chat_id"] == "326472368@lid"
    assert body[0]["already_linked"] is False


def test_create_manual_whatsapp_thread_link(user_client, db_session):
    tenant = create_tenant(db_session)
    payload = {
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "chat_id": "326472368@lid",
        "chat_display_name": "Alberto",
        "replace_existing": True,
    }
    response = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["chat_id"] == "326472368@lid"
    assert body["thread_id"] == tenant.id
    assert body["is_active"] is True
    assert body["linked_by_user_id"] == REGULAR_USER.id


def test_reject_duplicate_chat_linked_to_another_thread(user_client, db_session):
    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="B-dup-a")
    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="B-dup-b")
    payload = {
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "chat_id": "326472368@lid",
    }
    first = user_client.post(f"/api/threads/{tenant_a.id}/whatsapp-links", json=payload)
    assert first.status_code == 200

    second = user_client.post(f"/api/threads/{tenant_b.id}/whatsapp-links", json=payload)
    assert second.status_code == 409
    assert str(tenant_a.id) in second.json()["detail"]


def test_reject_second_active_link_without_replace_existing(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-second")
    payload_one = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "111@lid"}
    payload_two = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "222@lid"}

    first = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload_one)
    assert first.status_code == 200

    second = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload_two)
    assert second.status_code == 409

    third = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json={**payload_two, "replace_existing": True})
    assert third.status_code == 200
    assert third.json()["chat_id"] == "222@lid"

    links = user_client.get(f"/api/threads/{tenant.id}/whatsapp-links", params={"include_history": True}).json()
    old_link = next(link for link in links if link["chat_id"] == "111@lid")
    assert old_link["is_active"] is False
    assert old_link["unlinked_by_user_id"] == REGULAR_USER.id


def test_unlink_whatsapp_thread_link(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-unlink")
    payload = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "333@lid"}
    created = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload).json()

    delete_response = user_client.delete(f"/api/threads/{tenant.id}/whatsapp-links/{created['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["is_active"] is False

    active_links = user_client.get(f"/api/threads/{tenant.id}/whatsapp-links").json()
    assert active_links == []


def test_relink_chat_after_unlink_to_different_thread(user_client, db_session):
    tenant_a = create_tenant(db_session, booking_id="B-relink-a")
    tenant_b = create_tenant(db_session, booking_id="B-relink-b")
    payload = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "444@lid"}

    created = user_client.post(f"/api/threads/{tenant_a.id}/whatsapp-links", json=payload).json()
    user_client.delete(f"/api/threads/{tenant_a.id}/whatsapp-links/{created['id']}")

    response = user_client.post(f"/api/threads/{tenant_b.id}/whatsapp-links", json=payload)
    assert response.status_code == 200
    assert response.json()["thread_id"] == tenant_b.id


def test_permissions_require_authentication(client_without_webhook_secret, db_session):
    from app.core.dependencies import get_current_user as real_get_current_user

    app.dependency_overrides.pop(real_get_current_user, None)
    tenant = create_tenant(db_session, booking_id="B-perm")
    response = client_without_webhook_secret.post(
        f"/api/threads/{tenant.id}/whatsapp-links",
        json={"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "555@lid"},
    )
    assert response.status_code == 401


def test_create_link_triggers_background_resync(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-resync")
    payload = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "326472368@lid"}
    with patch("app.api.whatsapp_thread_links.resync_whatsapp_chat", new=AsyncMock(return_value={"ok": True, "fetched": 250})) as mocked_resync:
        response = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload)
    assert response.status_code == 200
    mocked_resync.assert_awaited_once_with("edi-crm-whatsapp", "326472368@lid")


def test_explicit_resync_endpoint_triggers_full_history_pull(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-resync-explicit")
    payload = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "326472368@lid"}
    with patch("app.api.whatsapp_thread_links.resync_whatsapp_chat", new=AsyncMock(return_value={"ok": True})):
        created = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload).json()

    with patch("app.api.whatsapp_thread_links.resync_whatsapp_chat", new=AsyncMock(return_value={"ok": True, "fetched": 250, "imported": 250, "deduped": 0, "failed": 0})) as mocked_resync:
        response = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links/{created['id']}/resync")
    assert response.status_code == 200
    mocked_resync.assert_awaited_once_with("edi-crm-whatsapp", "326472368@lid")
    body = response.json()
    assert body["resync"]["ok"] is True
    assert body["resync"]["fetched"] == 250
    assert body["resync"]["imported"] == 250
    assert body["link"]["chat_id"] == "326472368@lid"


def test_resync_reports_bridge_failure_without_erroring(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-resync-fail")
    payload = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "777@lid"}
    with patch("app.api.whatsapp_thread_links.resync_whatsapp_chat", new=AsyncMock(return_value={"ok": True})):
        created = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload).json()

    from app.services.whatsapp_client import WhatsAppBridgeError

    with patch("app.api.whatsapp_thread_links.resync_whatsapp_chat", new=AsyncMock(side_effect=WhatsAppBridgeError(503, "WhatsApp client is not ready"))):
        response = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links/{created['id']}/resync")
    assert response.status_code == 200
    body = response.json()
    assert body["resync"]["ok"] is False
    assert "not ready" in body["resync"]["error"]


def test_resync_rejects_unknown_link(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-resync-404")
    response = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links/999999/resync")
    assert response.status_code == 404


def test_manual_link_feeds_crm_backfill_identities_payload(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-backfill")
    payload = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "326472368@lid"}
    user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload)

    entries, trusted_identities, _, _ = _build_backfill_identity_entries(db_session, tenant_id=tenant.id)
    assert any("326472368@lid" in entry.chat_ids for entry in entries)
    assert any(identity.whatsapp_chat_id == "326472368@lid" for identity in trusted_identities)


def test_manual_link_resolves_inbound_message_deterministically(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-inbound")
    payload = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "326472368@lid"}
    user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload)

    resolved = resolve_tenant_for_inbound_channel(
        db_session,
        {
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "external_chat_namespace": "326472368@lid",
        },
        {},
        {},
    )
    assert resolved.tenant is not None
    assert resolved.tenant.id == tenant.id
    assert resolved.strategy == "exact_chat_endpoint"


def test_unlinked_chat_no_longer_resolves_inbound(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-unlink-inbound")
    payload = {"provider": "whatsapp-service", "external_account_id": "edi-crm-whatsapp", "chat_id": "666@lid"}
    created = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links", json=payload).json()
    user_client.delete(f"/api/threads/{tenant.id}/whatsapp-links/{created['id']}")

    resolved = resolve_tenant_for_inbound_channel(
        db_session,
        {
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "external_chat_namespace": "666@lid",
        },
        {},
        {},
    )
    assert resolved.tenant is None
