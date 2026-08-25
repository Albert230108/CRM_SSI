from datetime import datetime, timedelta, timezone

from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.gmail_integration import Conversation
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_conversation_link import TenantConversationLink
from app.services.ai_draft_trigger_service import register_inbound_message


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Trigger Tenant",
        booking_id="B-trigger-1",
        first_name="Sam",
        last_name="Doe",
        email="sam@example.com",
        check_in="2026-08-01",
        check_out="2026-08-05",
        room_name="Studio 1",
    )
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_no_trigger_when_auto_draft_disabled(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_email=False))
    db_session.commit()

    register_inbound_message(db_session, tenant=tenant, channel="email")
    db_session.commit()

    assert db_session.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).count() == 0


def test_no_trigger_when_no_ai_settings_row_exists(db_session):
    tenant = _create_tenant(db_session)
    register_inbound_message(db_session, tenant=tenant, channel="email")
    db_session.commit()
    assert db_session.query(AiAutoDraftTrigger).count() == 0


def test_creates_and_debounces_trigger(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_email=True))
    db_session.commit()

    register_inbound_message(db_session, tenant=tenant, channel="email", email_thread_id=5)
    db_session.commit()

    trigger = db_session.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).one()
    first_trigger_at = trigger.trigger_at
    assert trigger.channel == "email"
    assert trigger.email_thread_id == 5

    # A second inbound message resets (pushes out) the debounce timer rather than creating a
    # second row - the unique (tenant_id, channel) constraint on the model enforces this too.
    register_inbound_message(db_session, tenant=tenant, channel="email", email_thread_id=5)
    db_session.commit()

    triggers = db_session.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).all()
    assert len(triggers) == 1
    assert triggers[0].trigger_at >= first_trigger_at


def test_generate_draft_for_hidden_email_thread_returns_none(db_session, monkeypatch):
    from app.models.ai_reply_template import AiReplyTemplate
    from app.services import ai_auto_draft_service

    tenant = _create_tenant(db_session)
    template = AiReplyTemplate(name="Hidden Thread Template", sections=[], created_by_user_id=1)
    db_session.add(template)
    db_session.commit()
    db_session.add(TenantAiSettings(tenant_id=tenant.id, default_email_template_id=template.id, auto_draft_email=True))
    db_session.commit()

    conversation = Conversation(provider="gmail", provider_thread_id="hidden-thread")
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, is_visible=False))
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service.ai_agent_orchestrator, "resolve_drafter_context", lambda *args, **kwargs: ([], None))
    monkeypatch.setattr(ai_auto_draft_service.ai_agent_orchestrator, "latest_inbound_text", lambda *args, **kwargs: "Should not be used")
    monkeypatch.setattr(ai_auto_draft_service.ai_reply_service, "build_prompt_and_generate", lambda *args, **kwargs: "unexpected draft")

    trigger = AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", email_thread_id=conversation.id)
    result = ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger)

    assert result is None
    assert db_session.query(AiAutoDraft).count() == 0


def test_supersedes_pending_draft_on_new_message(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_whatsapp=True))
    db_session.commit()
    pending_draft = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="stale draft", status="pending")
    db_session.add(pending_draft)
    db_session.commit()

    register_inbound_message(db_session, tenant=tenant, channel="whatsapp")
    db_session.commit()
    db_session.refresh(pending_draft)

    assert pending_draft.status == "superseded"


def test_does_not_supersede_drafts_on_other_channels(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_email=True))
    db_session.commit()
    whatsapp_draft = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="unrelated", status="pending")
    db_session.add(whatsapp_draft)
    db_session.commit()

    register_inbound_message(db_session, tenant=tenant, channel="email")
    db_session.commit()
    db_session.refresh(whatsapp_draft)

    assert whatsapp_draft.status == "pending"
