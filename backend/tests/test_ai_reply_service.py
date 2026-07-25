from datetime import datetime, timedelta, timezone

from app.models.ai_reply_template import AiReplyTemplate
from app.models.communication import Communication
from app.models.finance import Finance
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.services import ai_reply_service


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Prompt Tenant",
        booking_id="B-prompt-1",
        first_name="Alex",
        last_name="Doe",
        email="alex@example.com",
        check_in="2026-08-01",
        check_out="2026-08-05",
        room_name="Studio 1",
        booking_status="confirmed",
    )
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _template(**overrides):
    defaults = dict(
        name="Test template",
        sections=[{"label": "Persona", "content": "You are a helpful host."}],
        include_history=False,
        history_message_limit=None,
        include_beds24=False,
        include_payments=False,
        created_by_user_id=1,
    )
    defaults.update(overrides)
    return AiReplyTemplate(**defaults)


def _capture_gemini_call(monkeypatch):
    captured = {}

    def fake_generate_text(system_prompt: str, user_message: str) -> str:
        captured["system_prompt"] = system_prompt
        captured["user_message"] = user_message
        return "Generated reply text"

    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text", fake_generate_text)
    return captured


def test_sections_are_concatenated_in_order(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template = _template(
        sections=[
            {"label": "Persona", "content": "You are a helpful host."},
            {"label": "Tone", "content": "Be warm and concise."},
        ]
    )
    captured = _capture_gemini_call(monkeypatch)

    result = ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="Let them know check-in is at 3pm."
    )

    assert result == "Generated reply text"
    assert captured["system_prompt"].index("Persona") < captured["system_prompt"].index("Tone")
    assert "You are a helpful host." in captured["system_prompt"]
    assert "Be warm and concise." in captured["system_prompt"]
    assert captured["user_message"] == "Let them know check-in is at 3pm."


def test_no_rough_draft_uses_generic_instruction(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template = _template()
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="whatsapp", rough_draft=None)

    assert "Draft a reply" in captured["user_message"]


def test_beds24_and_payments_blocks_only_appear_when_checked(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(Finance(tenant_id=tenant.id, type="charge", amount=100, currency="EUR", description="City tax"))
    db_session.add(Finance(tenant_id=tenant.id, type="payment", amount=100, currency="EUR", description="Deposit"))
    db_session.commit()

    captured = _capture_gemini_call(monkeypatch)
    template_off = _template(include_beds24=False, include_payments=False)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template_off, channel="email", rough_draft="hi")
    assert "Beds24" not in captured["system_prompt"]
    assert "Payments & Charges" not in captured["system_prompt"]

    template_on = _template(include_beds24=True, include_payments=True)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template_on, channel="email", rough_draft="hi")
    assert "Booking Information (Beds24)" in captured["system_prompt"]
    assert tenant.booking_id in captured["system_prompt"]
    assert "Payments & Charges" in captured["system_prompt"]
    assert "City tax" in captured["system_prompt"]


def test_history_is_channel_wide_not_thread_scoped(db_session, monkeypatch):
    tenant = _create_tenant(db_session)

    # Two separate email threads for the same tenant - history should span both, not just one.
    thread_a = Conversation(provider="gmail", provider_thread_id="thread-a", subject="Thread A")
    thread_b = Conversation(provider="gmail", provider_thread_id="thread-b", subject="Thread B")
    db_session.add_all([thread_a, thread_b])
    db_session.commit()
    db_session.add_all(
        [
            TenantConversationLink(tenant_id=tenant.id, conversation_id=thread_a.id),
            TenantConversationLink(tenant_id=tenant.id, conversation_id=thread_b.id),
        ]
    )
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            ConversationMessage(
                conversation_id=thread_a.id,
                provider="gmail",
                provider_message_id="msg-a1",
                direction="inbound",
                body="Message from thread A",
                sent_at=now - timedelta(days=2),
            ),
            ConversationMessage(
                conversation_id=thread_b.id,
                provider="gmail",
                provider_message_id="msg-b1",
                direction="inbound",
                body="Message from thread B",
                sent_at=now - timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_history=True, history_message_limit=10)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    assert "Message from thread A" in captured["system_prompt"]
    assert "Message from thread B" in captured["system_prompt"]


def test_history_respects_message_limit_and_channel(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    now = datetime.now(timezone.utc)
    for index in range(5):
        db_session.add(
            Communication(
                tenant_id=tenant.id,
                channel="whatsapp",
                direction="inbound",
                message=f"whatsapp message {index}",
                created_at=now - timedelta(minutes=5 - index),
            )
        )
    db_session.add(
        Communication(
            tenant_id=tenant.id,
            channel="email",
            direction="inbound",
            message="an email message, wrong channel",
            created_at=now,
        )
    )
    db_session.commit()

    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_history=True, history_message_limit=2)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="whatsapp", rough_draft="hi")

    # Only the 2 most recent WhatsApp messages, none of the email one.
    assert "whatsapp message 3" in captured["system_prompt"]
    assert "whatsapp message 4" in captured["system_prompt"]
    assert "whatsapp message 0" not in captured["system_prompt"]
    assert "wrong channel" not in captured["system_prompt"]
