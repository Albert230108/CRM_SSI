from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_channel_endpoint import TenantChannelEndpoint


def _create_tenant(db_session, name="AI Trigger Tenant", booking_id="B-ai-trigger-1"):
    tenant = Tenant(name=name, booking_id=booking_id, phone="+31600000000")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_whatsapp_endpoint(db_session, tenant_id, external_account_id="edi-crm-whatsapp"):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id=external_account_id,
        external_chat_namespace="31612345678@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()


def test_live_inbound_message_registers_a_trigger_when_auto_draft_enabled(client, db_session):
    tenant = _create_tenant(db_session)
    _create_whatsapp_endpoint(db_session, tenant.id)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_whatsapp=True))
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
            "whatsapp_message_id": "msg-ai-trigger-live",
            "timestamp": 1710000000,
            "message": "Live inbound message",
        },
    )
    assert response.status_code == 200

    triggers = db_session.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).all()
    assert len(triggers) == 1
    assert triggers[0].channel == "whatsapp"


def test_backfill_payload_does_not_register_a_trigger(client, db_session):
    tenant = _create_tenant(db_session, booking_id="B-ai-trigger-2")
    _create_whatsapp_endpoint(db_session, tenant.id)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_whatsapp=True))
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp/backfill-batch",
        json={
            "messages": [
                {
                    "direction": "inbound",
                    "provider": "whatsapp-service",
                    "external_account_id": "edi-crm-whatsapp",
                    "sender": "+31612345678",
                    "sender_normalized": "31612345678",
                    "whatsapp_chat_id": "31612345678@c.us",
                    "whatsapp_message_id": "msg-ai-trigger-backfill",
                    "timestamp": 1710000000,
                    "message": "Historical inbound message",
                    "source": "history",
                }
            ]
        },
    )
    assert response.status_code == 200

    assert db_session.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).count() == 0


def test_live_inbound_with_ambiguous_endpoints_still_captures_matched_endpoint(client, db_session):
    # Regression for the production bug: a tenant with two active WhatsApp endpoints on the
    # same account used to leave AiAutoDraftTrigger.whatsapp_endpoint_id NULL, so the later
    # auto-send couldn't tell which chat to reply in and silently failed. The inbound webhook
    # matches one specific endpoint by exact chat identity - that id must now reach the trigger.
    tenant = _create_tenant(db_session, booking_id="B-ai-trigger-ambiguous")
    _create_whatsapp_endpoint(db_session, tenant.id, external_account_id="edi-crm-whatsapp")
    matched_endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="99988877766@c.us",
        is_active=True,
    )
    db_session.add(matched_endpoint)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_whatsapp=True))
    db_session.commit()

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+99988877766",
            "sender_normalized": "99988877766",
            "whatsapp_chat_id": "99988877766@c.us",
            "whatsapp_message_id": "msg-ai-trigger-ambiguous",
            "timestamp": 1710000000,
            "message": "Live inbound message on the second chat",
        },
    )
    assert response.status_code == 200

    trigger = (
        db_session.query(AiAutoDraftTrigger)
        .filter(AiAutoDraftTrigger.tenant_id == tenant.id)
        .one()
    )
    assert trigger.whatsapp_endpoint_id == matched_endpoint.id
