"""
Tests for automatic WhatsApp chat resync triggers: on live inbound messages and on the
tenant-page-open resync-all endpoint. Both share a per-endpoint throttle
(app.services.whatsapp_auto_resync).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User
from app.services import whatsapp_auto_resync
from app.services.whatsapp_client import WhatsAppBridgeError

REGULAR_USER = User(id=2, email="agent-auto-resync@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def create_tenant(db_session, name="Auto Resync Tenant", booking_id="B-auto-resync"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_whatsapp_endpoint(
    db_session,
    tenant_id,
    external_account_id="edi-crm-whatsapp",
    external_chat_namespace="111@lid",
    is_active=True,
):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id=external_account_id,
        external_chat_namespace=external_chat_namespace,
        is_active=is_active,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint


@pytest.fixture(autouse=True)
def _reset_auto_resync_throttle():
    whatsapp_auto_resync._last_resync_at.clear()
    yield
    whatsapp_auto_resync._last_resync_at.clear()


def test_auto_resync_tenant_endpoints_resyncs_all_linked_chats(db_session):
    tenant = create_tenant(db_session)
    ep1 = create_whatsapp_endpoint(db_session, tenant.id, external_chat_namespace="111@lid")
    ep2 = create_whatsapp_endpoint(db_session, tenant.id, external_chat_namespace="222@lid")

    with patch(
        "app.services.whatsapp_auto_resync.resync_whatsapp_chat",
        new=AsyncMock(return_value={"ok": True, "fetched": 5, "imported": 5}),
    ) as mocked:
        summary = asyncio.run(whatsapp_auto_resync.auto_resync_tenant_endpoints(db_session, tenant.id))

    assert mocked.await_count == 2
    assert {item["endpoint_id"] for item in summary} == {ep1.id, ep2.id}
    assert all(item["status"] == "resynced" for item in summary)


def test_auto_resync_throttles_repeat_calls_within_window(db_session):
    tenant = create_tenant(db_session)
    endpoint = create_whatsapp_endpoint(db_session, tenant.id)

    with patch(
        "app.services.whatsapp_auto_resync.resync_whatsapp_chat", new=AsyncMock(return_value={"ok": True})
    ) as mocked:
        asyncio.run(whatsapp_auto_resync.auto_resync_tenant_endpoints(db_session, tenant.id))
        summary_second = asyncio.run(whatsapp_auto_resync.auto_resync_tenant_endpoints(db_session, tenant.id))

    assert mocked.await_count == 1
    assert summary_second == [{"endpoint_id": endpoint.id, "status": "throttled"}]


def test_auto_resync_one_endpoint_failure_does_not_block_others(db_session):
    tenant = create_tenant(db_session)
    ep1 = create_whatsapp_endpoint(db_session, tenant.id, external_chat_namespace="111@lid")
    ep2 = create_whatsapp_endpoint(db_session, tenant.id, external_chat_namespace="222@lid")

    async def fake_resync(external_account_id, chat_id):
        if chat_id == "111@lid":
            raise WhatsAppBridgeError(503, "boom")
        return {"ok": True}

    with patch("app.services.whatsapp_auto_resync.resync_whatsapp_chat", new=AsyncMock(side_effect=fake_resync)):
        summary = asyncio.run(whatsapp_auto_resync.auto_resync_tenant_endpoints(db_session, tenant.id))

    statuses = {item["endpoint_id"]: item["status"] for item in summary}
    assert statuses[ep1.id] == "error"
    assert statuses[ep2.id] == "resynced"


def test_inbound_webhook_triggers_auto_resync_for_tenant(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-webhook-trigger")
    create_whatsapp_endpoint(db_session, tenant.id, external_chat_namespace="31612345678@c.us")

    triggered = []
    monkeypatch.setattr("app.webhooks.whatsapp._trigger_auto_resync", lambda tenant_id: triggered.append(tenant_id))

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-trigger-1",
            "timestamp": 1710000000,
            "message": "Hi there",
        },
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == tenant.id
    assert triggered == [tenant.id]


def test_history_backfill_does_not_trigger_auto_resync(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-webhook-history")
    create_whatsapp_endpoint(db_session, tenant.id, external_chat_namespace="31699999999@c.us")

    triggered = []
    monkeypatch.setattr("app.webhooks.whatsapp._trigger_auto_resync", lambda tenant_id: triggered.append(tenant_id))

    response = client.post(
        "/webhooks/whatsapp/backfill-batch",
        json={
            "messages": [
                {
                    "direction": "inbound",
                    "provider": "whatsapp-service",
                    "external_account_id": "edi-crm-whatsapp",
                    "sender": "+31699999999",
                    "sender_normalized": "31699999999",
                    "whatsapp_chat_id": "31699999999@c.us",
                    "whatsapp_message_id": "msg-hist-1",
                    "timestamp": 1710000000,
                    "message": "Old message",
                    "source": "history",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert triggered == []


def test_resync_all_endpoint_resyncs_every_linked_chat_and_respects_throttle(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-resync-all")
    ep1 = create_whatsapp_endpoint(db_session, tenant.id, external_chat_namespace="111@lid")
    ep2 = create_whatsapp_endpoint(db_session, tenant.id, external_chat_namespace="222@lid")

    with patch(
        "app.api.whatsapp_thread_links.resync_whatsapp_chat", new=AsyncMock(return_value={"ok": True, "fetched": 3})
    ) as mocked:
        response = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links/resync-all")

    assert response.status_code == 200
    body = response.json()
    assert {item["link"]["id"] for item in body["results"]} == {ep1.id, ep2.id}
    assert all(item["resync"]["ok"] is True and item["resync"]["throttled"] is False for item in body["results"])
    assert mocked.await_count == 2

    # Immediately calling again is throttled per chat -- the whatsapp-service isn't hit again.
    with patch(
        "app.api.whatsapp_thread_links.resync_whatsapp_chat", new=AsyncMock(return_value={"ok": True})
    ) as mocked_second:
        response_second = user_client.post(f"/api/threads/{tenant.id}/whatsapp-links/resync-all")

    assert response_second.status_code == 200
    assert all(item["resync"]["throttled"] is True for item in response_second.json()["results"])
    mocked_second.assert_not_awaited()
