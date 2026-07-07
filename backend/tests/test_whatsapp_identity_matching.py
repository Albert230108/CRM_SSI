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


def test_whatsapp_identity_helper_requires_trusted_phone_for_lid():
    lid_identity = get_canonical_whatsapp_identity(
        {
            "direction": "inbound",
            "whatsapp_chat_id": "155066153590862@lid",
        },
        direction="inbound",
    )
    c_us_identity = get_canonical_whatsapp_identity(
        {
            "direction": "inbound",
            "whatsapp_chat_id": "31612345678@c.us",
        },
        direction="inbound",
    )
    zero_identity = get_canonical_whatsapp_identity(
        {
            "direction": "inbound",
            "whatsapp_chat_id": "0@c.us",
        },
        direction="inbound",
    )

    assert normalize_whatsapp_phone("+31 6 123 456 78") == "31612345678"
    assert normalize_whatsapp_chat_id("155066153590862@lid") == "155066153590862@lid"
    assert normalize_whatsapp_chat_id("123456789@G.US") == "123456789@g.us"
    assert lid_identity.raw_chat_id == "155066153590862@lid"
    assert lid_identity.normalized_phone is None
    assert lid_identity.canonical_chat_id == "155066153590862@lid"
    assert lid_identity.is_group is False
    assert c_us_identity.raw_chat_id == "31612345678@c.us"
    assert c_us_identity.normalized_phone == "31612345678"
    assert c_us_identity.canonical_chat_id == "31612345678"
    assert zero_identity.raw_chat_id == "0@c.us"
    assert zero_identity.normalized_phone is None
    assert zero_identity.canonical_chat_id == "0@c.us"
    assert zero_identity.is_group is False


def test_unrelated_lid_values_do_not_merge(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-wa-1")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    first = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_chat_id": "155066153590862@lid",
            "whatsapp_message_id": "msg-wa-lid-1",
            "message": "First lid message",
        },
    )
    second = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_chat_id": "155066153590863@lid",
            "whatsapp_message_id": "msg-wa-lid-2",
            "message": "Second lid message",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    saved = db_session.query(Communication).filter(Communication.tenant_id == tenant.id).order_by(Communication.id.asc()).all()
    assert len(saved) == 2
    assert {row.whatsapp_chat_id for row in saved} == {"155066153590862@lid", "155066153590863@lid"}
    assert {row.whatsapp_identity_key for row in saved} == {"155066153590862@lid", "155066153590863@lid"}
    assert {row.whatsapp_normalized_phone for row in saved} == {None}


def test_cus_and_lid_merge_when_trusted_phone_context_exists(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-wa-2")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    first = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31 6 123 456 78",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-wa-cus",
            "message": "First inbound message",
        },
    )
    second = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31 6 123 456 78",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "155066153590862@lid",
            "whatsapp_message_id": "msg-wa-lid",
            "message": "Second inbound message",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    saved = db_session.query(Communication).filter(Communication.tenant_id == tenant.id).order_by(Communication.id.asc()).all()
    assert len(saved) == 2
    assert {row.whatsapp_identity_key for row in saved} == {"31612345678"}
    assert {row.whatsapp_normalized_phone for row in saved} == {"31612345678"}
    assert {row.whatsapp_chat_id for row in saved} == {"31612345678@c.us", "155066153590862@lid"}


def test_group_chat_identity_stays_raw(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-wa-3")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31 6 123 456 78",
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
    assert saved.whatsapp_normalized_phone == "31612345678"


def test_outbound_whatsapp_duplicate_suppression_uses_provider_message_id(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-wa-4")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    payload = {
        "direction": "outbound",
        "provider": "whatsapp-service",
        "tenant_id": tenant.id,
        "external_account_id": "edi-crm-whatsapp",
        "whatsapp_chat_id": "31612345678@c.us",
        "recipient": "+31 6 123 456 78",
        "message": "Outbound duplicate test",
        "timestamp": 1710000000,
        "whatsapp_message_id": "msg-outbound-dup",
    }

    first = client.post("/webhooks/whatsapp", json=payload)
    second = client.post("/webhooks/whatsapp", json=payload)

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


def test_tenant_scoping_remains_intact(client, db_session):
    tenant_one = create_tenant(db_session, name="Tenant One", booking_id="B-wa-5")
    tenant_two = create_tenant(db_session, name="Tenant Two", booking_id="B-wa-6")
    create_whatsapp_endpoint(db_session, tenant_one.id, "edi-crm-whatsapp-a")
    create_whatsapp_endpoint(db_session, tenant_two.id, "edi-crm-whatsapp-b")

    first = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp-a",
            "sender": "+31 6 123 456 78",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-tenant-a",
            "message": "Tenant A message",
        },
    )
    second = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp-b",
            "sender": "+31 6 123 456 78",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-tenant-b",
            "message": "Tenant B message",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    tenant_one_rows = db_session.query(Communication).filter(Communication.tenant_id == tenant_one.id).all()
    tenant_two_rows = db_session.query(Communication).filter(Communication.tenant_id == tenant_two.id).all()
    assert len(tenant_one_rows) == 1
    assert len(tenant_two_rows) == 1
    assert tenant_one_rows[0].external_account_id == "edi-crm-whatsapp-a"
    assert tenant_two_rows[0].external_account_id == "edi-crm-whatsapp-b"
