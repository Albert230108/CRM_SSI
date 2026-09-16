import logging

import pytest

from app.models.ai_agent_run import STATUS_COMPLETED, STATUS_FAILED, AiAgentRun, AiAgentRunStep
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


def _answer_generate(text="An answer."):
    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return _result({"action": "answer", "answer": text})

    return fake_generate


def test_ask_creates_and_links_one_assistant_run(db_session, monkeypatch):
    conversation = _create_conversation(db_session, user_id=77)
    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", _answer_generate())

    ai_assistant_service.ask(db_session, conversation, "Where do I find tenants?")
    db_session.commit()
    db_session.refresh(conversation)

    runs = db_session.query(AiAgentRun).all()
    assert len(runs) == 1
    run = runs[0]
    assert conversation.agent_run_id == run.id
    assert run.channel == "assistant"
    assert run.mode == "manual"
    assert run.status == STATUS_COMPLETED
    assert run.created_by_user_id == 77
    assert run.tenant_id is None

    steps = db_session.query(AiAgentRunStep).filter(AiAgentRunStep.run_id == run.id).all()
    assert len(steps) == 1
    assert steps[0].stage == "assistant"
    assert steps[0].step_index == 0
    assert run.total_prompt_tokens == 1 and run.total_output_tokens == 1


def test_second_ask_reuses_same_run_and_appends_step(db_session, monkeypatch):
    conversation = _create_conversation(db_session)
    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", _answer_generate())

    ai_assistant_service.ask(db_session, conversation, "First question?")
    db_session.commit()
    db_session.refresh(conversation)
    first_run_id = conversation.agent_run_id

    ai_assistant_service.ask(db_session, conversation, "Second question?")
    db_session.commit()
    db_session.refresh(conversation)

    # Same run, updated rather than duplicated.
    assert conversation.agent_run_id == first_run_id
    assert db_session.query(AiAgentRun).count() == 1

    steps = (
        db_session.query(AiAgentRunStep)
        .filter(AiAgentRunStep.run_id == first_run_id)
        .order_by(AiAgentRunStep.step_index)
        .all()
    )
    assert [s.step_index for s in steps] == [0, 1]

    run = db_session.get(AiAgentRun, first_run_id)
    assert run.total_prompt_tokens == 2 and run.total_output_tokens == 2


def test_ask_uses_tenant_id_from_screen_context(db_session, monkeypatch):
    tenant = Tenant(name="Ctx Tenant", booking_id="B-ctx-1")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    conversation = _create_conversation(db_session)
    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", _answer_generate())

    ai_assistant_service.ask(
        db_session, conversation, "Question", screen_context={"tenantId": tenant.id}
    )
    db_session.commit()
    db_session.refresh(conversation)

    run = db_session.get(AiAgentRun, conversation.agent_run_id)
    assert run.tenant_id == tenant.id


def test_gemini_error_records_failed_run_step_and_logs(db_session, monkeypatch, caplog):
    conversation = _create_conversation(db_session)

    def fake_generate(*args, **kwargs):
        raise gemini_client.GeminiClientError("503 UNAVAILABLE")

    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", fake_generate)

    with caplog.at_level(logging.WARNING):
        message = ai_assistant_service.ask(db_session, conversation, "Anything?")
    db_session.commit()
    db_session.refresh(conversation)

    assert "couldn't answer" in message.content
    run = db_session.get(AiAgentRun, conversation.agent_run_id)
    assert run.status == STATUS_FAILED
    steps = db_session.query(AiAgentRunStep).filter(AiAgentRunStep.run_id == run.id).all()
    assert len(steps) == 1
    assert "503 UNAVAILABLE" in (steps[0].error or "")
    assert any("Gemini call failed" in r.getMessage() for r in caplog.records)
