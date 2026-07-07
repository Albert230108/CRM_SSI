from app.core.whatsapp_identity import get_canonical_whatsapp_identity, normalize_whatsapp_chat_id, normalize_whatsapp_phone
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint


def create_tenant(db_session, name="Tenant WhatsApp", booking_id="B-wa", phone=None, mobile=None):
    tenant = Tenant(name=name, booking_id=booking_id, phone=phone, mobile=mobile)
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


def test_whatsapp_identity_helper_preserves_group_ids_and_normalizes_phone():
    identity = get_canonical_whatsapp_identity(
        {
            "direction": "inbound",
            "whatsapp_chat_id": "155066153590862@lid",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
        },
        direction="inbound",
    )

    assert normalize_whatsapp_phone("+31 6 123 456 78") == "31612345678"
    assert normalize_whatsapp_chat_id("155066153590862@lid") == "155066153590862@lid"
    assert normalize_whatsapp_chat_id("123456789@G.US") == "123456789@g.us"
    assert identity.raw_chat_id == "155066153590862@lid"
    assert identity.normalized_phone == "31612345678"
    assert identity.canonical_chat_id == "31612345678"
    assert identity.is_group is False

    group_identity = get_canonical_whatsapp_identity(
        {
            "direction": "inbound",
            "whatsapp_chat_id": "123456789@g.us",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
        },
        direction="inbound",
    )
    assert group_identity.raw_chat_id == "123456789@g.us"
    assert group_identity.canonical_chat_id == "123456789@g.us"
    assert group_identity.is_group is True


def test_inbound_whatsapp_lid_and_cus_messages_resolve_to_same_identity(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-wa-1")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    first = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "155066153590862@lid",
            "whatsapp_message_id": "msg-wa-lid",
            "message": "First inbound message",
        },
    )
    second = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-wa-cus",
            "message": "Second inbound message",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    saved = db_session.query(Communication).filter(Communication.tenant_id == tenant.id).order_by(Communication.id.asc()).all()
    assert len(saved) == 2
    assert {row.whatsapp_identity_key for row in saved} == {"31612345678"}
    assert {row.whatsapp_normalized_phone for row in saved} == {"31612345678"}
    assert {row.whatsapp_chat_id for row in saved} == {"155066153590862@lid", "31612345678@c.us"}


def test_group_chat_identity_stays_raw(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-wa-2")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31612345678",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "123456789@g.us",
            "whatsapp_message_id": "msg-wa-group",
            "message": "Group message",
        },
    )

    assert response.status_code == 200
    saved = db_session.query(Communication).filter(Communication.provider_message_id == "msg-wa-group").one()
    assert saved.whatsapp_chat_id == "123456789@g.us"
    assert saved.whatsapp_identity_key == "123456789@g.us"


def test_outbound_whatsapp_duplicate_suppression_uses_canonical_identity(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-wa-3")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    payload = {
        "direction": "outbound",
        "provider": "whatsapp-service",
        "tenant_id": tenant.id,
        "external_account_id": "edi-crm-whatsapp",
        "message": "Outbound duplicate test",
        "timestamp": 1710000000,
    }

    first = client.post(
        "/webhooks/whatsapp",
        json={**payload, "whatsapp_chat_id": "31612345678@c.us", "recipient": "+31612345678"},
    )
    second = client.post(
        "/webhooks/whatsapp",
        json={**payload, "whatsapp_chat_id": "155066153590862@lid", "recipient": "+31612345678"},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    saved = db_session.query(Communication).filter(
        Communication.tenant_id == tenant.id,
        Communication.channel == "whatsapp",
        Communication.direction == "outbound",
    ).all()
    assert len(saved) == 1
    assert saved[0].whatsapp_identity_key == "31612345678"
    assert saved[0].whatsapp_normalized_phone == "31612345678"
