from datetime import datetime, timezone

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User
from app.services.whatsapp_client import WhatsAppBridgeError

SEND_FLOW_USER = User(id=3, email="send-flow-agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    # The shared `client` fixture only overrides get_current_admin_user; routes guarded by
    # get_current_user (like the send endpoint) need this override too.
    app.dependency_overrides[get_current_user] = lambda: SEND_FLOW_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def create_tenant(db_session, name="Tenant Outbound", booking_id="B-outbound", phone="+31600000000"):
    tenant = Tenant(name=name, booking_id=booking_id, phone=phone)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_whatsapp_endpoint(db_session, tenant_id, external_account_id, provider="whatsapp-service"):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider=provider,
        external_account_id=external_account_id,
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint


def test_whatsapp_send_payload_preserves_tenant_and_endpoint_identity(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-outbound-1")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    captured = {}

    async def fake_send_whatsapp_message(payload):
        captured.update(payload)
        return {
            "whatsapp_message_id": "msg-outbound-1",
            "whatsapp_chat_id": "15550000000@c.us",
            "tenant_id": payload["tenant_id"],
            "external_account_id": payload["external_account_id"],
            "whatsapp_endpoint_id": payload["whatsapp_endpoint_id"],
        }

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "whatsapp",
            "message": "Hello from tenant thread",
            "whatsapp_endpoint_id": endpoint.id,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["tenant_id"] == tenant.id
    assert payload["channel"] == "whatsapp"
    assert payload["direction"] == "outbound"
    assert payload["provider"] == "whatsapp-service"
    assert payload["external_account_id"] == "edi-crm-whatsapp"
    assert payload["whatsapp_chat_id"] == "15550000000@c.us"
    assert payload["provider_message_id"] == "msg-outbound-1"
    assert captured == {
        "to": "+31600000000",
        "message": "Hello from tenant thread",
        "tenant_id": tenant.id,
        "whatsapp_endpoint_id": endpoint.id,
        "external_account_id": "edi-crm-whatsapp",
    }

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-outbound-1").one()
    assert saved.tenant_id == tenant.id
    assert saved.external_account_id == "edi-crm-whatsapp"
    assert saved.provider == "whatsapp-service"


def test_whatsapp_send_targets_linked_chat_not_tenant_primary_phone(user_client, db_session, monkeypatch):
    """When the selected endpoint has a manually-linked chat (external_chat_namespace), the
    outbound send must go to that specific chat -- not the tenant's generic primary phone --
    otherwise a tenant with two chats linked on the same account could never reply to the
    second one (a reply would always land in the first/primary-phone chat)."""
    tenant = create_tenant(db_session, booking_id="B-outbound-linked-chat")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")
    endpoint.external_chat_namespace = "999888777@g.us"
    db_session.commit()

    captured = {}

    async def fake_send_whatsapp_message(payload):
        captured.update(payload)
        return {
            "whatsapp_message_id": "msg-outbound-linked",
            "whatsapp_chat_id": "999888777@g.us",
            "tenant_id": payload["tenant_id"],
            "external_account_id": payload["external_account_id"],
            "whatsapp_endpoint_id": payload["whatsapp_endpoint_id"],
        }

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "whatsapp",
            "message": "Hello from the group chat",
            "whatsapp_endpoint_id": endpoint.id,
        },
    )

    assert response.status_code == 201
    assert captured["to"] == "999888777@g.us"


def test_whatsapp_send_requires_specific_endpoint_when_account_has_multiple_chats(user_client, db_session, monkeypatch):
    """external_account_id alone can't disambiguate once a tenant has multiple active chats
    linked on that account and neither has ever received an inbound message -- there's no
    recency signal to default to, so the caller must pick a specific whatsapp_endpoint_id."""
    tenant = create_tenant(db_session, booking_id="B-outbound-ambiguous")
    first = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")
    first.external_chat_namespace = "111@lid"
    second = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")
    second.external_chat_namespace = "222@lid"
    db_session.commit()

    async def fake_send_whatsapp_message(payload):
        raise AssertionError("send_whatsapp_message should not be called for an ambiguous account selection")

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "whatsapp",
            "message": "Hello",
            "external_account_id": "edi-crm-whatsapp",
        },
    )

    assert response.status_code == 400
    assert "multiple chats" in response.json()["detail"]


def test_whatsapp_send_defaults_to_most_recent_inbound_chat_when_account_is_ambiguous(user_client, db_session, monkeypatch):
    """When a tenant has multiple active chats linked on the same account, sending with only
    external_account_id (no whatsapp_endpoint_id) should default to whichever chat most
    recently received an inbound message, instead of erroring out on the ambiguity."""
    tenant = create_tenant(db_session, booking_id="B-outbound-default-recent")
    older_endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")
    older_endpoint.external_chat_namespace = "111@lid"
    newer_endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")
    newer_endpoint.external_chat_namespace = "222@lid"
    db_session.commit()

    db_session.add_all(
        [
            Communication(
                tenant_id=tenant.id,
                channel="whatsapp",
                direction="inbound",
                provider="whatsapp-service",
                external_account_id="edi-crm-whatsapp",
                external_chat_namespace="111@lid",
                message="Hello from the older chat",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            Communication(
                tenant_id=tenant.id,
                channel="whatsapp",
                direction="inbound",
                provider="whatsapp-service",
                external_account_id="edi-crm-whatsapp",
                external_chat_namespace="222@lid",
                message="Hello from the newer chat",
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    captured = {}

    async def fake_send_whatsapp_message(payload):
        captured.update(payload)
        return {
            "whatsapp_message_id": "msg-outbound-default-recent",
            "whatsapp_chat_id": "222@lid",
            "tenant_id": payload["tenant_id"],
            "external_account_id": payload["external_account_id"],
            "whatsapp_endpoint_id": payload["whatsapp_endpoint_id"],
        }

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "whatsapp",
            "message": "Hello",
            "external_account_id": "edi-crm-whatsapp",
        },
    )

    assert response.status_code == 201
    assert captured["whatsapp_endpoint_id"] == newer_endpoint.id

    endpoints_response = user_client.get(f"/api/communications/tenants/{tenant.id}/whatsapp-endpoints")
    assert endpoints_response.status_code == 200
    flags = {row["id"]: row["is_most_recent_inbound"] for row in endpoints_response.json()}
    assert flags[newer_endpoint.id] is True
    assert flags[older_endpoint.id] is False


def test_whatsapp_send_returns_explicit_bridge_mismatch_error(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-outbound-2")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    async def fake_send_whatsapp_message(payload):
        raise WhatsAppBridgeError(
            400,
            "WhatsApp account id mismatch: requested swifthk-whatsapp but this service is configured for other-account",
        )

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "whatsapp",
            "message": "Hello from tenant thread",
            "whatsapp_endpoint_id": endpoint.id,
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["detail"] == "WhatsApp account id mismatch: requested swifthk-whatsapp but this service is configured for other-account"



def test_whatsapp_outbound_webhook_duplicate_callback_is_idempotent(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-outbound-3")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    async def fake_send_whatsapp_message(payload):
        return {
            "whatsapp_message_id": "msg-outbound-dup",
            "whatsapp_chat_id": "15550000000@c.us",
            "tenant_id": payload["tenant_id"],
            "external_account_id": payload["external_account_id"],
            "whatsapp_endpoint_id": payload["whatsapp_endpoint_id"],
        }

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "whatsapp",
            "message": "Hello duplicate callback",
            "whatsapp_endpoint_id": endpoint.id,
        },
    )
    assert response.status_code == 201

    outbound_payload = {
        "direction": "outbound",
        "provider": "whatsapp-service",
        "tenant_id": tenant.id,
        "external_account_id": "edi-crm-whatsapp",
        "whatsapp_chat_id": "15550000000@c.us",
        "whatsapp_message_id": "msg-outbound-dup",
        "message": "Hello duplicate callback",
        "recipient": "15550000000@c.us",
    }

    first = client.post("/webhooks/whatsapp", json=outbound_payload)
    second = client.post("/webhooks/whatsapp", json=outbound_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-outbound-dup").all()
    assert len(saved) == 1
    assert saved[0].tenant_id == tenant.id
    assert saved[0].external_account_id == "edi-crm-whatsapp"



def test_whatsapp_outbound_webhook_before_backend_write_is_deduped_by_provider_message_id(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-outbound-4")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    async def fake_send_whatsapp_message(payload):
        return {
            "whatsapp_message_id": "msg-outbound-race",
            "whatsapp_chat_id": "15550000001@c.us",
            "tenant_id": payload["tenant_id"],
            "external_account_id": payload["external_account_id"],
            "whatsapp_endpoint_id": payload["whatsapp_endpoint_id"],
        }

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    webhook_payload = {
        "direction": "outbound",
        "provider": "whatsapp-service",
        "tenant_id": tenant.id,
        "external_account_id": "edi-crm-whatsapp",
        "whatsapp_chat_id": "15550000001@c.us",
        "whatsapp_message_id": "msg-outbound-race",
        "message": "Hello race window",
        "recipient": "15550000001@c.us",
    }

    webhook_response = client.post("/webhooks/whatsapp", json=webhook_payload)
    assert webhook_response.status_code == 200

    response = client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "whatsapp",
            "message": "Hello race window",
            "whatsapp_endpoint_id": endpoint.id,
        },
    )
    assert response.status_code == 201

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-outbound-race").all()
    assert len(saved) == 1
    assert saved[0].tenant_id == tenant.id
    assert saved[0].whatsapp_chat_id == "15550000001@c.us"



def test_whatsapp_outbound_webhook_without_provider_message_id_uses_chat_account_fallback(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-outbound-5")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    async def fake_send_whatsapp_message(payload):
        return {
            "whatsapp_message_id": "msg-outbound-fallback",
            "whatsapp_chat_id": "15550000002@c.us",
            "tenant_id": payload["tenant_id"],
            "external_account_id": payload["external_account_id"],
            "whatsapp_endpoint_id": payload["whatsapp_endpoint_id"],
        }

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "whatsapp",
            "message": "Hello fallback window",
            "whatsapp_endpoint_id": endpoint.id,
        },
    )
    assert response.status_code == 201

    webhook_response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "outbound",
            "provider": "whatsapp-service",
            "tenant_id": tenant.id,
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_chat_id": "15550000002@c.us",
            "message": "Hello fallback window",
            "recipient": "15550000002@c.us",
        },
    )

    assert webhook_response.status_code == 200
    saved = db_session.query(Communication).filter(Communication.tenant_id == tenant.id, Communication.external_account_id == "edi-crm-whatsapp", Communication.whatsapp_chat_id == "15550000002@c.us").all()
    assert len(saved) == 1
    assert saved[0].provider_message_id == "msg-outbound-fallback"



def test_distinct_historical_outbound_messages_in_same_chat_do_not_clobber_each_other(client, db_session):
    # Regression test: two distinct real WhatsApp outbound messages in the same chat, synced
    # via history backfill in the same account, must land as two separate rows with their own
    # text and timestamp — not merged into one via the identity-key fallback matcher.
    tenant = create_tenant(db_session, booking_id="B-outbound-no-clobber")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    older = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "outbound",
            "source": "history",
            "provider": "whatsapp-service",
            "tenant_id": tenant.id,
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-history-outbound-older",
            "timestamp": 1700000000,  # 2023-11-14
            "message": "Older outbound message",
        },
    )
    newer = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "outbound",
            "source": "history",
            "provider": "whatsapp-service",
            "tenant_id": tenant.id,
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-history-outbound-newer",
            "timestamp": 1783684740,  # 2026-07-10
            "message": "why wont you sync?",
        },
    )

    assert older.status_code == 200
    assert newer.status_code == 200

    saved = (
        db_session.query(Communication)
        .filter(Communication.tenant_id == tenant.id, Communication.channel == "whatsapp", Communication.direction == "outbound")
        .order_by(Communication.created_at.asc())
        .all()
    )
    assert len(saved) == 2, "each distinct message must get its own row, not overwrite the other"

    by_id = {row.provider_message_id: row for row in saved}
    assert by_id["msg-history-outbound-older"].message == "Older outbound message"
    assert by_id["msg-history-outbound-newer"].message == "why wont you sync?"
    # The newer message's own timestamp must not have leaked onto the older row (or vice versa).
    assert by_id["msg-history-outbound-older"].created_at < by_id["msg-history-outbound-newer"].created_at


def test_resync_self_heals_a_previously_corrupted_outbound_row(client, db_session):
    # Simulates the aftermath of the old bug: a row whose provider_message_id already matches
    # the true message (so it WILL be found by the exact-ID lookup) but whose created_at was
    # left wrong by a prior buggy import. Re-syncing that exact message must correct created_at.
    tenant = create_tenant(db_session, booking_id="B-outbound-selfheal")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    corrupted = Communication(
        tenant_id=tenant.id,
        channel="whatsapp",
        direction="outbound",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        whatsapp_chat_id="31612345678@c.us",
        whatsapp_identity_key="31612345678@c.us",
        provider_message_id="msg-history-outbound-newer",
        message="why wont you sync?",
        created_at=datetime(2026, 2, 7, tzinfo=timezone.utc),
    )
    db_session.add(corrupted)
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "outbound",
            "source": "history",
            "provider": "whatsapp-service",
            "tenant_id": tenant.id,
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-history-outbound-newer",
            "timestamp": 1783684740,  # 2026-07-10
            "message": "why wont you sync?",
        },
    )
    assert response.status_code == 200

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-history-outbound-newer").all()
    assert len(saved) == 1
    db_session.refresh(saved[0])
    assert saved[0].created_at.year == 2026
    assert saved[0].created_at.month == 7


def test_live_inbound_whatsapp_message_appears_in_grouped_thread(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-inbound-1")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")
    endpoint.external_chat_namespace = "31612345678@c.us"
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-live-inbound-1",
            "timestamp": 1710000000,
            "message": "Live inbound message",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "exact_chat_endpoint"
    assert payload["tenant_id"] == tenant.id

    thread_response = client.get(f"/api/communications/tenants/{tenant.id}/grouped-thread")
    assert thread_response.status_code == 200
    thread_payload = thread_response.json()
    assert thread_payload["tenant_id"] == tenant.id
    assert len(thread_payload["items"]) == 1
    group = thread_payload["items"][0]
    assert group["type"] == "whatsapp_group"
    assert group["message_count"] == 1
    assert group["messages"][0]["provider_message_id"] == "msg-live-inbound-1"
    assert group["messages"][0]["message"] == "Live inbound message"



def test_backfilled_whatsapp_message_appears_in_grouped_thread(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-inbound-2")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")
    endpoint.external_chat_namespace = "31612345678@c.us"
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-backfill-inbound-1",
            "timestamp": 1700000000,
            "message": "Historical inbound message",
        },
    )

    assert response.status_code == 200
    thread_response = client.get(f"/api/communications/tenants/{tenant.id}/grouped-thread")
    assert thread_response.status_code == 200
    thread_payload = thread_response.json()
    assert len(thread_payload["items"]) == 1
    group = thread_payload["items"][0]
    assert group["type"] == "whatsapp_group"
    assert group["message_count"] == 1
    assert group["messages"][0]["provider_message_id"] == "msg-backfill-inbound-1"
    assert group["messages"][0]["message"] == "Historical inbound message"

def test_backfilled_whatsapp_outbound_message_uses_phone_tenant(client, db_session):
    phone_tenant = create_tenant(db_session, booking_id="B-inbound-2b")
    phone_tenant.phone = "+31 6 12345678"
    account_tenant = create_tenant(db_session, booking_id="B-inbound-2c")
    create_whatsapp_endpoint(db_session, account_tenant.id, "edi-crm-whatsapp")

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "outbound",
            "source": "history",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "recipient": "+31612345678",
            "to": "+31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-backfill-outbound-1",
            "timestamp": 1700000001,
            "message": "Historical outbound message",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "legacy_phone_inference"
    assert payload["tenant_id"] == phone_tenant.id

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-backfill-outbound-1").all()
    assert len(saved) == 1
    assert saved[0].tenant_id == phone_tenant.id
    assert saved[0].message == "Historical outbound message"



def test_duplicate_backfill_without_provider_message_id_does_not_create_duplicate_rows(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-inbound-3")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")
    payload = {
        "direction": "inbound",
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "sender": "+31612345678",
        "sender_normalized": "31612345678",
        "whatsapp_chat_id": "31612345678@c.us",
        "timestamp": 1690000000,
        "message": "Duplicate backfill without provider id",
    }

    first = client.post("/webhooks/whatsapp", json=payload)
    second = client.post("/webhooks/whatsapp", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200

    saved = db_session.query(Communication).filter(
        Communication.tenant_id == tenant.id,
        Communication.channel == "whatsapp",
        Communication.direction == "inbound",
    ).all()
    assert len(saved) == 1
    assert saved[0].provider_message_id is None
    assert saved[0].message == "Duplicate backfill without provider id"

    thread_response = client.get(f"/api/communications/tenants/{tenant.id}/grouped-thread")
    thread_payload = thread_response.json()
    assert len(thread_payload["items"]) == 1
    assert thread_payload["items"][0]["message_count"] == 1



def test_duplicate_backfill_with_provider_message_id_does_not_create_duplicate_rows(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-inbound-3b")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")
    payload = {
        "direction": "inbound",
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "sender": "+31612345678",
        "sender_normalized": "31612345678",
        "whatsapp_chat_id": "31612345678@c.us",
        "whatsapp_message_id": "msg-duplicate-with-id",
        "timestamp": 1690000100,
        "message": "Duplicate backfill with provider id",
    }

    first = client.post("/webhooks/whatsapp", json=payload)
    second = client.post("/webhooks/whatsapp", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200

    saved = db_session.query(Communication).filter(
        Communication.tenant_id == tenant.id,
        Communication.channel == "whatsapp",
        Communication.direction == "inbound",
        Communication.provider_message_id == "msg-duplicate-with-id",
    ).all()
    assert len(saved) == 1
    assert saved[0].message == "Duplicate backfill with provider id"


def test_out_of_order_whatsapp_arrival_renders_in_chronological_order(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-inbound-4")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    newer = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-out-of-order-newer",
            "timestamp": 1710000200,
            "message": "Newer message",
        },
    )
    older = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-out-of-order-older",
            "timestamp": 1710000100,
            "message": "Older message",
        },
    )

    assert newer.status_code == 200
    assert older.status_code == 200

    thread_response = client.get(f"/api/communications/tenants/{tenant.id}/grouped-thread")
    assert thread_response.status_code == 200
    thread_payload = thread_response.json()
    assert len(thread_payload["items"]) == 1
    messages = thread_payload["items"][0]["messages"]
    assert [message["provider_message_id"] for message in messages] == ["msg-out-of-order-older", "msg-out-of-order-newer"]
    assert [message["message"] for message in messages] == ["Older message", "Newer message"]
