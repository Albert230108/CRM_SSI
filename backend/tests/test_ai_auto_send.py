from datetime import datetime, timedelta, timezone

from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.ai_reply_template import AiReplyTemplate
from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User
from app.services import ai_auto_draft_service, ai_reply_service


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Auto Send Tenant",
        booking_id="B-auto-send-1",
        first_name="Sam",
        last_name="Doe",
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


def _create_user(db_session):
    user = User(email="auto-send-owner@example.com", password_hash="x", is_active=True, is_admin=False)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_generate_draft_schedules_auto_send_when_enabled(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    user = _create_user(db_session)
    template = AiReplyTemplate(name="T", sections=[{"label": "Persona", "content": "Be helpful."}], created_by_user_id=user.id)
    db_session.add(template)
    db_session.flush()
    db_session.add(TenantAiSettings(tenant_id=tenant.id, default_email_template_id=template.id, auto_draft_email=True, auto_send_email=True))
    db_session.commit()

    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", lambda prompt: "Auto reply")

    trigger = AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))
    draft = ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger)
    db_session.commit()

    assert draft.status == "pending_auto_send"
    assert draft.scheduled_send_at is not None
    # SQLite drops tzinfo on round-trip through commit/refresh, unlike Postgres in production -
    # normalize before comparing so this assertion isn't a false failure of the test DB dialect.
    scheduled_send_at = draft.scheduled_send_at if draft.scheduled_send_at.tzinfo else draft.scheduled_send_at.replace(tzinfo=timezone.utc)
    assert scheduled_send_at > datetime.now(timezone.utc)


def test_generate_draft_stays_pending_when_auto_send_disabled(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    user = _create_user(db_session)
    template = AiReplyTemplate(name="T", sections=[{"label": "Persona", "content": "Be helpful."}], created_by_user_id=user.id)
    db_session.add(template)
    db_session.flush()
    db_session.add(TenantAiSettings(tenant_id=tenant.id, default_email_template_id=template.id, auto_draft_email=True, auto_send_email=False))
    db_session.commit()

    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", lambda prompt: "Auto reply")

    trigger = AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))
    draft = ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger)
    db_session.commit()

    assert draft.status == "pending"
    assert draft.scheduled_send_at is None


def test_send_scheduled_draft_email_success_marks_sent_and_ai_generated(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    account = GmailAccount(email_address="inbox@example.com", is_active=True)
    db_session.add(account)
    db_session.flush()
    conversation = Conversation(provider="gmail", provider_account_id=account.id, provider_thread_id="thread-1", subject="Hi")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id="msg-1",
            direction="inbound",
            sender_email="tenant@example.com",
            subject="Hi",
            body="When is check-in?",
            sent_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    db_session.commit()

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="email",
        email_thread_id=conversation.id,
        generated_text="Check-in is at 3pm",
        formatted_text="<p>Check-in is at <strong>3pm</strong></p>",
        status="pending_auto_send",
        scheduled_send_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service, "build_gmail_credentials", lambda account: object())
    captured = {}

    def fake_send_gmail_reply(credentials, **kwargs):
        captured.update(kwargs)
        return {"id": "gmail-msg-id"}

    monkeypatch.setattr(ai_auto_draft_service, "send_gmail_reply", fake_send_gmail_reply)

    result, failure_reason = ai_auto_draft_service.send_scheduled_draft(db_session, draft)
    db_session.commit()

    assert result is True
    assert failure_reason is None
    assert draft.status == "sent"
    assert draft.sent_communication_id is not None
    communication = db_session.query(Communication).filter(Communication.id == draft.sent_communication_id).first()
    assert communication.ai_generated is True
    assert communication.message == "Check-in is at 3pm"
    assert captured["body_text"] == "Check-in is at 3pm"
    assert captured["body_html"] == "<p>Check-in is at <strong>3pm</strong></p>"


def test_send_scheduled_draft_email_failure_leaves_draft_pending_auto_send(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    account = GmailAccount(email_address="inbox2@example.com", is_active=True)
    db_session.add(account)
    db_session.flush()
    conversation = Conversation(provider="gmail", provider_account_id=account.id, provider_thread_id="thread-2", subject="Hi")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id="msg-2",
            direction="inbound",
            sender_email="tenant2@example.com",
            subject="Hi",
            body="When is check-in?",
            sent_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    db_session.commit()

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="email",
        email_thread_id=conversation.id,
        generated_text="Check-in is at 3pm",
        status="pending_auto_send",
        scheduled_send_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service, "build_gmail_credentials", lambda account: object())

    def failing_send(credentials, **kwargs):
        raise RuntimeError("gmail api down")

    monkeypatch.setattr(ai_auto_draft_service, "send_gmail_reply", failing_send)

    result, failure_reason = ai_auto_draft_service.send_scheduled_draft(db_session, draft)

    assert result is False
    assert failure_reason == "Failed to send Gmail reply"
    assert draft.status == "pending_auto_send"
    assert draft.sent_communication_id is None


def test_send_scheduled_draft_whatsapp_success(db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-auto-send-wa-1")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="31612345678@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="whatsapp",
        whatsapp_endpoint_id=endpoint.id,
        generated_text="Check-in is at 3pm",
        formatted_text="*Check-in* is at 3pm",
        status="pending_auto_send",
        scheduled_send_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(draft)
    db_session.commit()

    sent_payloads = []

    async def fake_send_whatsapp_message(payload):
        sent_payloads.append(payload)
        return {"whatsapp_message_id": "wamid-auto-1"}

    monkeypatch.setattr(ai_auto_draft_service, "send_whatsapp_message", fake_send_whatsapp_message)

    result, failure_reason = ai_auto_draft_service.send_scheduled_draft(db_session, draft)
    db_session.commit()

    assert result is True
    assert failure_reason is None
    assert draft.status == "sent"
    communication = db_session.query(Communication).filter(Communication.id == draft.sent_communication_id).first()
    assert communication.ai_generated is True
    assert communication.channel == "whatsapp"
    assert communication.message == "*Check-in* is at 3pm"
    assert sent_payloads[0]["message"] == "*Check-in* is at 3pm"


def test_send_scheduled_draft_whatsapp_html_formatted_text_falls_back_to_generated_text(db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-auto-send-wa-html")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="31612345678@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="whatsapp",
        whatsapp_endpoint_id=endpoint.id,
        generated_text="Check-in is at 3pm",
        formatted_text="<p>Check-in is at <strong>3pm</strong></p>",
        status="pending_auto_send",
        scheduled_send_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(draft)
    db_session.commit()

    sent_payloads = []

    async def fake_send_whatsapp_message(payload):
        sent_payloads.append(payload)
        return {"whatsapp_message_id": "wamid-auto-html-1"}

    def fake_persist(db, **kwargs):
        class _Result:
            communication = type("_Communication", (), {"id": 2})()

        return _Result()

    monkeypatch.setattr(ai_auto_draft_service, "send_whatsapp_message", fake_send_whatsapp_message)
    monkeypatch.setattr(ai_auto_draft_service, "persist_whatsapp_outbound_communication", fake_persist)

    result, failure_reason = ai_auto_draft_service.send_scheduled_draft(db_session, draft)

    assert result is True
    assert failure_reason is None
    assert sent_payloads[0]["message"] == "Check-in is at 3pm"


def test_send_scheduled_draft_whatsapp_ambiguous_endpoint_fails(db_session):
    tenant = _create_tenant(db_session, booking_id="B-auto-send-wa-2")
    # Two active endpoints and no whatsapp_endpoint_id captured - can't tell which chat to use.
    db_session.add_all(
        [
            TenantChannelEndpoint(tenant_id=tenant.id, channel_type="whatsapp", provider="whatsapp-service", external_account_id="acct-a", external_chat_namespace="a@c.us", is_active=True),
            TenantChannelEndpoint(tenant_id=tenant.id, channel_type="whatsapp", provider="whatsapp-service", external_account_id="acct-b", external_chat_namespace="b@c.us", is_active=True),
        ]
    )
    db_session.commit()

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="whatsapp",
        generated_text="Check-in is at 3pm",
        status="pending_auto_send",
        scheduled_send_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(draft)
    db_session.commit()

    result, failure_reason = ai_auto_draft_service.send_scheduled_draft(db_session, draft)

    assert result is False
    assert failure_reason == "This tenant has multiple WhatsApp chats linked; link a specific one for this draft"
    assert draft.status == "pending_auto_send"
