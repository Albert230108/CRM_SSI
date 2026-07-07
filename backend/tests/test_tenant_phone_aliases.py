from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_phone_alias import TenantPhoneAlias
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services.tenant_phone_aliases import sync_tenant_phone_aliases


def create_tenant(db_session, name="Tenant Alias", booking_id="B-alias", phone="+31 6 1111 1111", mobile="0031 6 2222 2222"):
    tenant = Tenant(name=name, booking_id=booking_id, phone=phone, mobile=mobile)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    sync_tenant_phone_aliases(db_session, tenant, primary_phone=tenant.phone, alias_phones=[tenant.mobile])
    db_session.commit()
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


def test_alias_table_stores_primary_and_secondary_numbers(db_session):
    tenant = create_tenant(db_session)

    aliases = db_session.query(TenantPhoneAlias).filter(TenantPhoneAlias.tenant_id == tenant.id).order_by(TenantPhoneAlias.is_primary.desc(), TenantPhoneAlias.id.asc()).all()

    assert [alias.normalized_phone for alias in aliases] == ["31611111111", "31622222222"]
    assert [alias.is_primary for alias in aliases] == [True, False]
    assert aliases[0].raw_phone == "+31 6 1111 1111"
    assert aliases[1].raw_phone == "0031 6 2222 2222"


def test_whatsapp_inbound_routes_both_trusted_numbers_to_one_tenant(client, db_session):
    tenant = create_tenant(db_session, booking_id="B-alias-inbound")
    create_whatsapp_endpoint(db_session, tenant.id)

    first = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "sender": "+31 6 1111 1111",
            "sender_normalized": "31611111111",
            "whatsapp_message_id": "msg-alias-primary",
            "message": "Primary number message",
        },
    )
    second = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "sender": "0031 6 2222 2222",
            "sender_normalized": "31622222222",
            "whatsapp_message_id": "msg-alias-secondary",
            "message": "Secondary number message",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["tenant_id"] == tenant.id
    assert second.json()["tenant_id"] == tenant.id

    saved = db_session.query(Communication).filter(Communication.tenant_id == tenant.id, Communication.channel == "whatsapp").order_by(Communication.id.asc()).all()
    assert len(saved) == 2
    assert {row.whatsapp_normalized_phone for row in saved} == {"31611111111", "31622222222"}


def test_whatsapp_send_uses_primary_alias_number(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-alias-send")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id)

    captured = {}

    async def fake_send_whatsapp_message(payload):
        captured.update(payload)
        return {
            "whatsapp_message_id": "msg-alias-send",
            "whatsapp_chat_id": "31611111111@c.us",
            "tenant_id": payload["tenant_id"],
            "external_account_id": payload["external_account_id"],
            "whatsapp_endpoint_id": payload["whatsapp_endpoint_id"],
        }

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "whatsapp",
            "message": "Alias send test",
            "whatsapp_endpoint_id": endpoint.id,
        },
    )

    assert response.status_code == 201
    assert captured["to"] == "+31 6 1111 1111"
