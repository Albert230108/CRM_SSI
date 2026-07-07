from datetime import datetime, timezone

from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint


def create_tenant(db_session, name="Tenant Secure", booking_id="B-secure"):
    tenant = Tenant(name=name, booking_id=booking_id, phone="+31600000000")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_whatsapp_endpoint(db_session, tenant_id, external_account_id="edi-crm-whatsapp"):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id=external_account_id,
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint


def test_whatsapp_webhook_accepts_valid_secret(client, db_session):
    tenant = create_tenant(db_session)
    create_whatsapp_endpoint(db_session, tenant.id)

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-webhook-secret-valid",
            "timestamp": 1710000000,
            "message": "Secret validated inbound message",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["tenant_id"] == tenant.id
    assert body["routing_strategy"] == "account_identity"


def test_whatsapp_webhook_rejects_missing_secret(client_without_webhook_secret, db_session):
    tenant = create_tenant(db_session, booking_id="B-secure-missing")
    create_whatsapp_endpoint(db_session, tenant.id)

    response = client_without_webhook_secret.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-webhook-secret-missing",
            "timestamp": 1710000001,
            "message": "Missing secret inbound message",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "Missing webhook secret"


def test_whatsapp_webhook_rejects_wrong_secret(client_without_webhook_secret, db_session):
    tenant = create_tenant(db_session, booking_id="B-secure-wrong")
    create_whatsapp_endpoint(db_session, tenant.id)

    response = client_without_webhook_secret.post(
        "/webhooks/whatsapp",
        headers={"X-Webhook-Secret": "wrong-secret"},
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-webhook-secret-wrong",
            "timestamp": 1710000002,
            "message": "Wrong secret inbound message",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == "Invalid webhook secret"


def test_whatsapp_backfill_identities_exports_crm_known_chat_keys(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-secure-identities")
    tenant.phone = "+31 6 1234 5678"
    tenant.mobile = "0031 6 9876 5432"
    db_session.commit()
    create_whatsapp_endpoint(db_session, tenant.id)
    db_session.add(
        Communication(
            tenant_id=tenant.id,
            channel="whatsapp",
            direction="inbound",
            provider="whatsapp-service",
            external_account_id="edi-crm-whatsapp",
            whatsapp_chat_id="31612345678@c.us",
            message="Mapped inbound message",
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    response = client.get("/webhooks/whatsapp/backfill-identities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["total_tenants"] == 1
    assert payload["total_active_endpoints"] == 1
    assert payload["total_identity_records"] >= 3
    entry = payload["entries"][0]
    assert entry["tenant_id"] == tenant.id
    assert "31612345678" in entry["phone_numbers"]
    assert "3098765432" in entry["phone_numbers"]
    assert "31612345678@c.us" in entry["chat_ids"]
