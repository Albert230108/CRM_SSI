from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services.whatsapp_client import WhatsAppBridgeError


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
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")

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
    assert payload["external_account_id"] == "swifthk-whatsapp"
    assert payload["whatsapp_chat_id"] == "15550000000@c.us"
    assert payload["provider_message_id"] == "msg-outbound-1"
    assert captured == {
        "to": "+31600000000",
        "message": "Hello from tenant thread",
        "tenant_id": tenant.id,
        "whatsapp_endpoint_id": endpoint.id,
        "external_account_id": "swifthk-whatsapp",
    }

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-outbound-1").one()
    assert saved.tenant_id == tenant.id
    assert saved.external_account_id == "swifthk-whatsapp"
    assert saved.provider == "whatsapp-service"


def test_whatsapp_send_returns_explicit_bridge_mismatch_error(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-outbound-2")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")

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
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")

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
        "external_account_id": "swifthk-whatsapp",
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
    assert saved[0].external_account_id == "swifthk-whatsapp"



def test_whatsapp_outbound_webhook_before_backend_write_is_deduped_by_provider_message_id(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-outbound-4")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")

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
        "external_account_id": "swifthk-whatsapp",
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
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")

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
            "external_account_id": "swifthk-whatsapp",
            "whatsapp_chat_id": "15550000002@c.us",
            "message": "Hello fallback window",
            "recipient": "15550000002@c.us",
        },
    )

    assert webhook_response.status_code == 200
    saved = db_session.query(Communication).filter(Communication.tenant_id == tenant.id, Communication.external_account_id == "swifthk-whatsapp", Communication.whatsapp_chat_id == "15550000002@c.us").all()
    assert len(saved) == 1
    assert saved[0].provider_message_id == "msg-outbound-fallback"



def test_live_inbound_whatsapp_message_appears_in_grouped_thread(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-inbound-1")
    create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "swifthk-whatsapp",
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
    assert payload["routing_strategy"] == "account_identity"
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
    create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "swifthk-whatsapp",
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



def test_duplicate_backfill_without_provider_message_id_does_not_create_duplicate_rows(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-inbound-3")
    create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")
    payload = {
        "direction": "inbound",
        "provider": "whatsapp-service",
        "external_account_id": "swifthk-whatsapp",
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
    create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")
    payload = {
        "direction": "inbound",
        "provider": "whatsapp-service",
        "external_account_id": "swifthk-whatsapp",
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
    create_whatsapp_endpoint(db_session, tenant.id, "swifthk-whatsapp")

    newer = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "swifthk-whatsapp",
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
            "external_account_id": "swifthk-whatsapp",
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
