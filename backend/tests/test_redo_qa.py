import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.ai_agent_profile import MEMORY_REDO_ROLE, AiAgentProfile
from app.models.ai_agent_run import AiAgentRun, AiAgentRunStep
from app.models.redo_request_log import RedoRequestLog
from app.models.redo_qa_message import RedoQaMessage
from app.models.tenant import Tenant
from app.models.user import User
from app.services import gemini_client, redo_qa_service

QA_USER = User(id=7, email="redo-qa@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: QA_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Redo QA Tenant", booking_id="B-redo-qa-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_redo_log(db_session, tenant, **overrides):
    defaults = dict(channel="crm", what="make it shorter", why="staff wants less detail", ai_agent_run_id=None)
    defaults.update(overrides)
    redo_log = RedoRequestLog(tenant_id=tenant.id, **defaults)
    db_session.add(redo_log)
    db_session.commit()
    db_session.refresh(redo_log)
    return redo_log


def _create_run_with_long_step(db_session, tenant, **overrides):
    defaults = dict(channel="crm", mode="manual", status="completed", planner_profile_id=None)
    defaults.update(overrides)
    run = AiAgentRun(tenant_id=tenant.id, **defaults)
    db_session.add(run)
    db_session.flush()
    long_prompt = "P" * 5000
    long_response = "R" * 5000
    db_session.add(
        AiAgentRunStep(
            run_id=run.id,
            step_index=0,
            stage="planner",
            model="fake-model",
            prompt=long_prompt,
            response=long_response,
        )
    )
    db_session.commit()
    db_session.refresh(run)
    return run, long_prompt, long_response


def test_build_context_text_includes_instructions_and_full_run_log_without_truncation(db_session):
    tenant = _create_tenant(db_session)
    run, long_prompt, long_response = _create_run_with_long_step(db_session, tenant)
    redo_log = _create_redo_log(db_session, tenant, ai_agent_run_id=run.id)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True, instructions="Be specific and honest."))
    db_session.commit()

    parts = redo_qa_service.build_context_parts(db_session, redo_log)

    assert parts["what"] == "make it shorter"
    assert parts["why"] == "staff wants less detail"
    assert parts["instructions"] == "Be specific and honest."
    assert long_prompt in parts["run_log_text"]
    assert long_response in parts["run_log_text"]
    assert "[...truncated]" not in parts["run_log_text"]
    assert "What to change: make it shorter" in parts["context_text"]
    assert "Be specific and honest." in parts["context_text"]
    assert long_prompt in parts["context_text"]


def test_answer_question_persists_both_turns_and_grounds_on_context(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    run, long_prompt, long_response = _create_run_with_long_step(db_session, tenant)
    redo_log = _create_redo_log(db_session, tenant, ai_agent_run_id=run.id)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True, instructions="Be specific and honest."))
    db_session.commit()

    captured_prompt = {}

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompt["prompt"] = prompt
        return gemini_client.GenerationResult(text="Because it was too verbose.", parsed=None, model="fake", prompt_tokens=1, output_tokens=1, latency_ms=1)

    monkeypatch.setattr(redo_qa_service.gemini_client, "generate", fake_generate)

    assistant_message = redo_qa_service.answer_question(db_session, redo_log, "Why was this redone?", asked_by_user_id=QA_USER.id)
    db_session.commit()

    assert assistant_message.content == "Because it was too verbose."
    assert assistant_message.ai_agent_run_id is not None
    assert long_prompt in captured_prompt["prompt"]
    assert long_response in captured_prompt["prompt"]
    assert "Be specific and honest." in captured_prompt["prompt"]

    messages = db_session.query(RedoQaMessage).filter(RedoQaMessage.redo_request_log_id == redo_log.id).order_by(RedoQaMessage.id).all()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Why was this redone?"
    assert messages[1].role == "assistant"
    assert messages[1].content == "Because it was too verbose."
    assert messages[1].ai_agent_run_id == assistant_message.ai_agent_run_id

    run_row = db_session.query(AiAgentRun).filter(AiAgentRun.id == assistant_message.ai_agent_run_id).one()
    assert run_row.tenant_id == tenant.id
    assert run_row.channel == "qa"
    assert run_row.mode == "manual"
    assert run_row.status == "completed"
    assert run_row.total_prompt_tokens == 1
    assert run_row.total_output_tokens == 1

    step = db_session.query(AiAgentRunStep).filter(AiAgentRunStep.run_id == run_row.id).one()
    assert step.stage == "qa"
    assert step.prompt == captured_prompt["prompt"]
    assert step.response == "Because it was too verbose."
    assert step.prompt_tokens == 1
    assert step.output_tokens == 1
    assert step.error is None


def test_answer_question_records_failed_run_when_gemini_errors(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    run, _, _ = _create_run_with_long_step(db_session, tenant)
    redo_log = _create_redo_log(db_session, tenant, ai_agent_run_id=run.id)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True, instructions="Be specific and honest."))
    db_session.commit()

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        raise gemini_client.GeminiClientError("boom")

    monkeypatch.setattr(redo_qa_service.gemini_client, "generate", fake_generate)

    assistant_message = redo_qa_service.answer_question(db_session, redo_log, "Why was this redone?", asked_by_user_id=QA_USER.id)
    db_session.commit()

    assert assistant_message.content == "Sorry, I couldn't answer that right now - please try again."
    assert assistant_message.ai_agent_run_id is not None

    run_row = db_session.query(AiAgentRun).filter(AiAgentRun.id == assistant_message.ai_agent_run_id).one()
    assert run_row.tenant_id == tenant.id
    assert run_row.channel == "qa"
    assert run_row.mode == "manual"
    assert run_row.status == "failed"
    assert run_row.total_prompt_tokens == 0
    assert run_row.total_output_tokens == 0

    step = db_session.query(AiAgentRunStep).filter(AiAgentRunStep.run_id == run_row.id).one()
    assert step.stage == "qa"
    assert step.error == "boom"
    assert step.response is None
    assert step.prompt_tokens is None
    assert step.output_tokens is None


def test_redo_qa_endpoints_return_context_and_persist_history(user_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    run, long_prompt, _ = _create_run_with_long_step(db_session, tenant)
    redo_log = _create_redo_log(db_session, tenant, ai_agent_run_id=run.id)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True, instructions="Be specific and honest."))
    db_session.commit()

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(text="It was too long.", parsed=None, model="fake", prompt_tokens=1, output_tokens=1, latency_ms=1)

    monkeypatch.setattr(redo_qa_service.gemini_client, "generate", fake_generate)

    context_response = user_client.get(f"/api/redo-requests/{redo_log.id}/qa/context")
    assert context_response.status_code == 200
    context = context_response.json()
    assert context["what"] == "make it shorter"
    assert context["instructions"] == "Be specific and honest."
    assert long_prompt in context["run_log_text"]

    ask_response = user_client.post(f"/api/redo-requests/{redo_log.id}/qa", json={"question": "What exactly was too long?"})
    assert ask_response.status_code == 201
    ask_payload = ask_response.json()
    assert ask_payload["content"] == "It was too long."
    assert ask_payload["ai_agent_run_id"] is not None

    history_response = user_client.get(f"/api/redo-requests/{redo_log.id}/qa")
    assert history_response.status_code == 200
    history = history_response.json()
    roles = [message["role"] for message in history]
    assert roles == ["user", "assistant"]
    assert history[1]["ai_agent_run_id"] == ask_payload["ai_agent_run_id"]


def test_redo_qa_context_404_for_missing_log(user_client):
    response = user_client.get("/api/redo-requests/999999/qa/context")
    assert response.status_code == 404
