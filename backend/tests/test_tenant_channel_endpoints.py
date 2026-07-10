from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services.tenant_channel_resolver import resolve_tenant_for_inbound_channel


def create_tenant(db_session, name="Tenant A", booking_id="B-1", tenant_id=None):
    tenant = Tenant(id=tenant_id, name=name, booking_id=booking_id) if tenant_id is not None else Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_duplicate_endpoint_prevention(client, db_session):
    tenant = create_tenant(db_session)
    payload = {
        "tenant_id": tenant.id,
        "channel_type": "whatsapp",
        "provider": "whatsapp-service",
        "external_account_id": "client-1",
        "external_chat_namespace": "client-1-chat@c.us",
        "webhook_token": "token-1",
    }
    r1 = client.post("/api/admin/tenant-channel-endpoints", json=payload)
    assert r1.status_code == 200
    r2 = client.post("/api/admin/tenant-channel-endpoints", json=payload)
    assert r2.status_code == 400

    payload2 = {**payload, "external_chat_namespace": "client-1-chat-2@c.us"}
    r3 = client.post("/api/admin/tenant-channel-endpoints", json=payload2)
    assert r3.status_code == 400


def test_max_two_active_whatsapp_services_per_tenant(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-max-2")

    payload_one = {
        "tenant_id": tenant.id,
        "channel_type": "whatsapp",
        "provider": "whatsapp-service",
        "external_account_id": "client-1",
        "external_chat_namespace": "client-1-chat@c.us",
    }
    payload_two = {
        "tenant_id": tenant.id,
        "channel_type": "whatsapp",
        "provider": "whatsapp-service",
        "external_account_id": "client-2",
        "external_chat_namespace": "client-2-chat@c.us",
    }
    payload_three = {
        "tenant_id": tenant.id,
        "channel_type": "whatsapp",
        "provider": "whatsapp-service",
        "external_account_id": "client-3",
        "external_chat_namespace": "client-3-chat@c.us",
    }

    first = client.post("/api/admin/tenant-channel-endpoints", json=payload_one)
    second = client.post("/api/admin/tenant-channel-endpoints", json=payload_two)
    third = client.post("/api/admin/tenant-channel-endpoints", json=payload_three)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 400
    assert third.json()["detail"] == "A tenant can only link up to 2 active WhatsApp services"


def test_tenant_resolution_by_webhook_token(db_session):
    tenant = create_tenant(db_session, name="Tenant B", booking_id="B-2")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="client-2",
        webhook_token="route-token",
        signing_secret="secret-1",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    result = resolve_tenant_for_inbound_channel(db_session, {"webhook_token": "route-token"}, {}, {})
    assert result.tenant.id == tenant.id
    assert result.strategy == "webhook_token"


def test_inbound_whatsapp_known_exact_chat_routes_to_tenant_88(client, db_session):
    tenant = create_tenant(db_session, name="Tenant C", booking_id="B-3", tenant_id=88)
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="31900000000@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31900000000",
            "sender_normalized": "31900000000",
            "whatsapp_chat_id": "31900000000@c.us",
            "whatsapp_message_id": "msg-known-account-88",
            "message": "Hello from the mapped account",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "exact_chat_endpoint"
    assert payload["tenant_id"] == 88
    assert payload["unresolved_reason"] is None

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-known-account-88").all()
    assert len(saved) == 1
    assert saved[0].tenant_id == 88

def test_inbound_whatsapp_history_source_routes_by_exact_chat_endpoint(client, db_session):
    phone_tenant = create_tenant(db_session, name="Tenant History Phone", booking_id="B-3b")
    phone_tenant.phone = "+31 6 12345678"
    account_tenant = create_tenant(db_session, name="Tenant History Account", booking_id="B-3c", tenant_id=88)
    endpoint = TenantChannelEndpoint(
        tenant_id=account_tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="31612345678@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "source": "history",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-history-phone-match",
            "message": "Historical inbound message",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "exact_chat_endpoint"
    assert payload["tenant_id"] == 88
    assert payload["unresolved_reason"] is None

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-history-phone-match").all()
    assert len(saved) == 1
    assert saved[0].tenant_id == 88
    assert saved[0].message == "Historical inbound message"

def test_inactive_endpoint_ignored(db_session):
    tenant = create_tenant(db_session, name="Tenant D", booking_id="B-4")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="client-4",
        webhook_token="route-token-4",
        is_active=False,
    )
    db_session.add(endpoint)
    db_session.commit()

    result = resolve_tenant_for_inbound_channel(db_session, {"webhook_token": "route-token-4", "provider": "whatsapp-service", "external_account_id": "client-4"}, {}, {})
    assert result.tenant is None
    assert result.strategy == "unresolved"


def test_inbound_whatsapp_ambiguous_phone_match_remains_unresolved(client, db_session):
    tenant_one = create_tenant(db_session, name="Tenant E", booking_id="B-5")
    tenant_one.phone = "+31 6 12345678"
    tenant_two = create_tenant(db_session, name="Tenant F", booking_id="B-6")
    tenant_two.mobile = "0031 6 12345678"
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "client-5",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_message_id": "msg-123",
            "message": "Hello there",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "ambiguous_phone_match"
    assert payload["unresolved_reason"] == "ambiguous_phone_match"
    assert payload["tenant_id"] is None

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-123").all()
    assert saved == []

def test_fallback_still_works_for_unmigrated_tenants(db_session):
    tenant = create_tenant(db_session, name="Tenant G", booking_id="B-7")
    tenant.phone = "+31 6 12345678"
    db_session.commit()

    result = resolve_tenant_for_inbound_channel(db_session, {"sender": "+31612345678"}, {}, {})
    assert result.tenant.id == tenant.id
    assert result.strategy == "legacy_phone_inference"


def test_inbound_whatsapp_unknown_account_identity_remains_unresolved(client, db_session):
    tenant = create_tenant(db_session, name="Tenant WhatsApp Account", booking_id="B-8")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="different-account",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "unknown-whatsapp-account",
            "sender": "+31999999999",
            "sender_normalized": "31999999999",
            "whatsapp_message_id": "msg-account-identity",
            "message": "Hello from account identity",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "unresolved"
    assert payload["unresolved_reason"] == "no_deterministic_match"
    assert payload["tenant_id"] is None

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-account-identity").all()
    assert saved == []

def test_inbound_whatsapp_exact_chat_endpoint_beats_phone_match(client, db_session):
    phone_tenant = create_tenant(db_session, name="Tenant WhatsApp Phone", booking_id="B-9")
    phone_tenant.phone = "+31 6 12345678"
    account_tenant = create_tenant(db_session, name="Tenant WhatsApp Account Priority", booking_id="B-10", tenant_id=88)
    endpoint = TenantChannelEndpoint(
        tenant_id=account_tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="31612345678@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
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
            "whatsapp_message_id": "msg-phone-priority",
            "message": "Hello from account identity",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "exact_chat_endpoint"
    assert payload["tenant_id"] == 88
    assert payload["unresolved_reason"] is None

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-phone-priority").all()
    assert len(saved) == 1
    assert saved[0].tenant_id == 88

def test_inbound_whatsapp_remains_unrouted_without_phone_or_account_identity(client, db_session):
    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "unknown-whatsapp-account",
            "sender": "+31988888888",
            "sender_normalized": "31988888888",
            "whatsapp_message_id": "msg-unrouted",
            "message": "Hello from nowhere",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "unresolved"
    assert payload["unresolved_reason"] == "no_deterministic_match"
    assert payload["tenant_id"] is None

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-unrouted").all()
    assert saved == []

async def fake_whatsapp_booking(booking_id):
    return {
        "id": booking_id,
        "roomName": "Studio 1",
        "arrival": "2026-07-01",
        "departure": "2026-07-02",
        "invoiceItems": [],
    }

def test_inbound_whatsapp_routes_after_import_when_chat_is_linked(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.tenants.fetch_booking_with_invoice", fake_whatsapp_booking)
    response = client.post("/api/tenants/import", json={
        "booking_id": "IMPORT-WA-1",
        "name": "Tenant Import WhatsApp",
        "first_name": "WhatsApp",
        "last_name": "Import",
        "check_in": "2026-07-07",
        "check_out": "2026-07-08",
    })
    assert response.status_code == 200
    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "IMPORT-WA-1").first()
    assert tenant is not None

    endpoint = db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == tenant.id).first()
    assert endpoint is not None
    endpoint.external_chat_namespace = "31912345678@c.us"
    db_session.commit()

    webhook = client.post('/webhooks/whatsapp', json={
        "direction": "inbound",
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "sender": "+31912345678",
        "sender_normalized": "31912345678",
        "whatsapp_chat_id": "31912345678@c.us",
        "whatsapp_message_id": "msg-import-created-mapping",
        "message": "Hello after import",
    })
    assert webhook.status_code == 200
    payload = webhook.json()
    assert payload["routing_strategy"] == "exact_chat_endpoint"
    assert payload["tenant_id"] == tenant.id
    assert payload["unresolved_reason"] is None

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-import-created-mapping").all()
    assert len(saved) == 1
    assert saved[0].tenant_id == tenant.id



def test_inbound_whatsapp_unresolved_when_chat_identity_missing(client, db_session):
    tenant = create_tenant(db_session, name="Tenant Missing Chat", booking_id="B-missing-chat")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="15550000000@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_message_id": "msg-missing-chat-id",
            "message": "Missing chat identity",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "missing_chat_identity"
    assert payload["unresolved_reason"] == "missing_chat_identity"
    assert payload["tenant_id"] is None

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-missing-chat-id").all()
    assert saved == []


def test_inbound_whatsapp_unresolved_when_wrong_chat_for_service(client, db_session):
    tenant = create_tenant(db_session, name="Tenant Wrong Chat", booking_id="B-wrong-chat")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="15551112222@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_chat_id": "15553334444@c.us",
            "sender": "+31900000000",
            "sender_normalized": "31900000000",
            "whatsapp_message_id": "msg-wrong-chat-id",
            "message": "Wrong chat identity",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "unresolved"
    assert payload["unresolved_reason"] == "no_exact_chat_match"
    assert payload["tenant_id"] is None

    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-wrong-chat-id").all()
    assert saved == []


def test_inbound_whatsapp_account_fallback_only_for_legacy_unlinked_endpoint(client, db_session, monkeypatch):
    monkeypatch.setenv("CRM_WHATSAPP_ALLOW_ACCOUNT_LEVEL_ENDPOINT_FALLBACK", "true")
    tenant = create_tenant(db_session, name="Tenant Account Fallback", booking_id="B-account-fallback")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace=None,
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_message_id": "msg-account-fallback",
            "message": "Legacy fallback route",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "account_identity_fallback"
    assert payload["tenant_id"] == tenant.id


def test_inbound_whatsapp_fallback_enabled_still_requires_chat_for_migrated_endpoint(client, db_session, monkeypatch):
    monkeypatch.setenv("CRM_WHATSAPP_ALLOW_ACCOUNT_LEVEL_ENDPOINT_FALLBACK", "true")
    tenant = create_tenant(db_session, name="Tenant Migrated Endpoint", booking_id="B-account-fallback-2")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="15550000000@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_message_id": "msg-account-fallback-blocked",
            "message": "Missing chat with migrated endpoint",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_strategy"] == "missing_chat_identity"
    assert payload["unresolved_reason"] == "missing_chat_identity"
    assert payload["tenant_id"] is None