import pytest

from app.models.app_knowledge_entry import AppKnowledgeEntry
from app.models.assistant_conversation import AssistantConversation
from app.models.assistant_message import AssistantMessage
from app.models.tenant import Tenant
from app.services import ai_assistant_service, gemini_client


def _create_conversation(db_session, user_id=42):
    conversation = ai_assistant_service.create_conversation(db_session, user_id)
    db_session.commit()
    db_session.refresh(conversation)
    return conversation


def _result(parsed: dict):
    return gemini_client.GenerationResult(text="ignored", parsed=parsed, model="fake", prompt_tokens=1, output_tokens=1, latency_ms=1)


def test_answer_only_loop_persists_both_turns(db_session, monkeypatch):
    conversation = _create_conversation(db_session)

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return _result({"action": "answer", "answer": "Tenants live on the dashboard's tenant list."})

    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", fake_generate)

    assistant_message = ai_assistant_service.ask(db_session, conversation, "Where do I find tenants?")
    db_session.commit()

    assert assistant_message.content == "Tenants live on the dashboard's tenant list."
    messages = (
        db_session.query(AssistantMessage)
        .filter(AssistantMessage.conversation_id == conversation.id)
        .order_by(AssistantMessage.id)
        .all()
    )
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "Where do I find tenants?"
    # A short first question becomes the conversation's title.
    db_session.refresh(conversation)
    assert conversation.title == "Where do I find tenants?"


def test_use_tools_then_answer_loop_calls_gemini_twice_and_records_trace(db_session, monkeypatch):
    conversation = _create_conversation(db_session)
    db_session.add(AppKnowledgeEntry(title="Deposits", body="Deposits are set on the tenant's finance tab."))
    db_session.commit()

    calls = []

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        calls.append(prompt)
        if len(calls) == 1:
            return _result({"action": "use_tools", "requests": [{"tool": "search_knowledge_base", "query": "deposit"}]})
        return _result({"action": "answer", "answer": "Deposits are set on the tenant's finance tab."})

    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", fake_generate)

    assistant_message = ai_assistant_service.ask(db_session, conversation, "Where do I set a deposit?")
    db_session.commit()

    assert len(calls) == 2
    assert "Deposits are set on the tenant's finance tab." in calls[1]  # tool result fed into the second call
    assert assistant_message.content == "Deposits are set on the tenant's finance tab."
    assert assistant_message.tool_trace["steps"][0]["tool"] == "search_knowledge_base"


def test_search_crm_and_tenant_context_tools_are_disabled_without_use_crm(db_session, monkeypatch):
    conversation = _create_conversation(db_session)

    captured = {}

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured.setdefault("prompts", []).append(prompt)
        if len(captured["prompts"]) == 1:
            return _result({"action": "use_tools", "requests": [{"tool": "search_crm", "query": "smith"}]})
        return _result({"action": "answer", "answer": "I can't search the CRM right now."})

    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", fake_generate)

    ai_assistant_service.ask(db_session, conversation, "Find tenant Smith", use_crm=False)
    db_session.commit()

    assert "turned off" in captured["prompts"][1]


def test_get_tenant_context_tool_returns_live_booking_fields(db_session, monkeypatch):
    conversation = _create_conversation(db_session)
    tenant = Tenant(name="Jane Doe", booking_id="B-assist-1", room_name="Studio 3")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    captured = {}

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured.setdefault("prompts", []).append(prompt)
        if len(captured["prompts"]) == 1:
            return _result({"action": "use_tools", "requests": [{"tool": "get_tenant_context", "tenant_id": tenant.id}]})
        return _result({"action": "answer", "answer": "Jane Doe is in Studio 3."})

    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", fake_generate)

    ai_assistant_service.ask(db_session, conversation, "Which room is Jane Doe in?", use_crm=True)
    db_session.commit()

    assert "Jane Doe" in captured["prompts"][1]
    assert "Studio 3" in captured["prompts"][1]


def test_knowledge_suggestion_is_surfaced_but_not_saved(db_session, monkeypatch):
    conversation = _create_conversation(db_session)

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return _result(
            {
                "action": "answer",
                "answer": "Refunds are processed manually today.",
                "knowledge_suggestion": {"title": "Refunds", "body": "Refunds are processed manually today."},
            }
        )

    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", fake_generate)

    assistant_message = ai_assistant_service.ask(db_session, conversation, "How do refunds work?")
    db_session.commit()

    assert assistant_message.tool_trace["knowledge_suggestion"] == {"title": "Refunds", "body": "Refunds are processed manually today."}
    assert db_session.query(AppKnowledgeEntry).count() == 0


def test_gemini_error_returns_fallback_message(db_session, monkeypatch):
    conversation = _create_conversation(db_session)

    def fake_generate(*args, **kwargs):
        raise gemini_client.GeminiClientError("boom")

    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", fake_generate)

    assistant_message = ai_assistant_service.ask(db_session, conversation, "Anything?")
    db_session.commit()

    assert "couldn't answer" in assistant_message.content
