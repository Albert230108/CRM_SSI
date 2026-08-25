"""Confirms outbound WhatsApp/Gmail sends register the brain-writer and action-writer debounce
triggers, same as inbound messages already did - the fix for "whenever there is a new message
in/out" (previously trigger registration only ever happened on inbound).
"""
from datetime import datetime, timezone

from app.models.action_writer_trigger import ActionWriterTrigger
from app.models.gmail_integration import Conversation, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_brain_trigger import TenantBrainTrigger
from app.services.email_outbound_persistence import persist_gmail_outbound_message
from app.services.whatsapp_outbound_persistence import persist_whatsapp_outbound_communication


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Outbound Trigger Tenant", booking_id="B-outbound-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _enable_both_writers(db_session, tenant):
    db_session.add(TenantAiSettings(tenant_id=tenant.id, brain_writer_enabled=True, action_writer_enabled=True))
    db_session.commit()


def test_outbound_whatsapp_send_registers_both_triggers(db_session):
    tenant = _create_tenant(db_session)
    _enable_both_writers(db_session, tenant)

    persist_whatsapp_outbound_communication(
        db_session,
        tenant_id=tenant.id,
        provider="whatsapp-service",
        external_account_id="acct-1",
        external_phone_id=None,
        external_chat_namespace=None,
        whatsapp_chat_id="31612345678@c.us",
        whatsapp_identity_key="31612345678",
        whatsapp_normalized_phone="31612345678",
        provider_message_id="wamsg-1",
        subject=None,
        message="Sure, see you at 3pm.",
        created_at=datetime.now(timezone.utc),
    )

    assert db_session.query(TenantBrainTrigger).filter(TenantBrainTrigger.tenant_id == tenant.id, TenantBrainTrigger.channel == "whatsapp").count() == 1
    assert db_session.query(ActionWriterTrigger).filter(ActionWriterTrigger.tenant_id == tenant.id, ActionWriterTrigger.channel == "whatsapp").count() == 1


def test_outbound_whatsapp_dedupe_does_not_register_a_second_trigger(db_session):
    tenant = _create_tenant(db_session)
    _enable_both_writers(db_session, tenant)

    kwargs = dict(
        tenant_id=tenant.id,
        provider="whatsapp-service",
        external_account_id="acct-1",
        external_phone_id=None,
        external_chat_namespace=None,
        whatsapp_chat_id="31612345678@c.us",
        whatsapp_identity_key="31612345678",
        whatsapp_normalized_phone="31612345678",
        provider_message_id="wamsg-2",
        subject=None,
        message="Confirmed.",
        created_at=datetime.now(timezone.utc),
    )
    persist_whatsapp_outbound_communication(db_session, **kwargs)
    first_trigger = db_session.query(TenantBrainTrigger).filter(TenantBrainTrigger.tenant_id == tenant.id).one()
    first_trigger_at = first_trigger.trigger_at

    # Same provider_message_id -> matched as the same message ("deduped"), not a new one - must
    # not push the debounce timer out again.
    persist_whatsapp_outbound_communication(db_session, **kwargs)

    triggers = db_session.query(TenantBrainTrigger).filter(TenantBrainTrigger.tenant_id == tenant.id).all()
    assert len(triggers) == 1
    assert triggers[0].trigger_at == first_trigger_at


def test_outbound_gmail_send_registers_both_triggers(db_session):
    tenant = _create_tenant(db_session)
    _enable_both_writers(db_session, tenant)
    account = GmailAccount(email_address="inbox@example.com", is_active=True)
    db_session.add(account)
    db_session.commit()
    conversation = Conversation(provider="gmail", provider_account_id=account.id, provider_thread_id="thread-outbound-1", subject="Hi")
    db_session.add(conversation)
    db_session.commit()

    persist_gmail_outbound_message(
        db_session,
        tenant_id=tenant.id,
        conversation=conversation,
        account=account,
        to_email="guest@example.com",
        subject="Re: Hi",
        message="Sure, see you then.",
        gmail_result={"id": "gmail-msg-1"},
    )

    assert db_session.query(TenantBrainTrigger).filter(TenantBrainTrigger.tenant_id == tenant.id, TenantBrainTrigger.channel == "email").count() == 1
    assert db_session.query(ActionWriterTrigger).filter(ActionWriterTrigger.tenant_id == tenant.id, ActionWriterTrigger.channel == "email").count() == 1


def test_outbound_send_does_not_register_trigger_when_writers_disabled(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, brain_writer_enabled=False, action_writer_enabled=False))
    db_session.commit()

    persist_whatsapp_outbound_communication(
        db_session,
        tenant_id=tenant.id,
        provider="whatsapp-service",
        external_account_id="acct-1",
        external_phone_id=None,
        external_chat_namespace=None,
        whatsapp_chat_id="31612345678@c.us",
        whatsapp_identity_key="31612345678",
        whatsapp_normalized_phone="31612345678",
        provider_message_id="wamsg-3",
        subject=None,
        message="OK.",
        created_at=datetime.now(timezone.utc),
    )

    assert db_session.query(TenantBrainTrigger).count() == 0
    assert db_session.query(ActionWriterTrigger).count() == 0
