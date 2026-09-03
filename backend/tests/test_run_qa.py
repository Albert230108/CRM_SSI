import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.ai_agent_profile import RUN_QA_ROLE, AiAgentProfile
from app.models.ai_agent_run import AiAgentRun, AiAgentRunStep
from app.models.run_qa_message import RunQaMessage
from app.models.tenant import Tenant
from app.models.user import User
from app.services import gemini_client, run_qa_service

QA_USER = User(id=8, email="run-qa@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: QA_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Run QA Tenant", booking_id="B-run-qa-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_run_with_long_step(db_session, tenant, *, stage="planner", **overrides):
    """A subject run (planner/brain_writer/action_writer) with one long step, to prove no truncation."""
    defaults = dict(channel="whatsapp", mode="brain_writer", status="completed", planner_profile_id=None)
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
            stage=stage,
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
    run, long_prompt, long_response = _create_run_with_long_step(db_session, tenant, stage="brain_writer")
    db_session.add(
        AiAgentProfile(
            name="Run QA",
            role=RUN_QA_ROLE,
            is_default=True,
            instructions="Be specific and honest.",
            model="gemini-test-qa",
            temperature=0.25,
            max_output_tokens=321,
        )
    )
    db_session.commit()

    parts = run_qa_service.build_context_parts(db_session, run)

    assert f"run_id={run.id}" in parts["run_summary"]
    assert "mode=brain_writer" in parts["run_summary"]
    assert parts["instructions"] == "Be specific and honest."
    assert long_prompt in parts["run_log_text"]
    assert long_response in parts["run_log_text"]
    assert "[...truncated]" not in parts["run_log_text"]
    assert f"run_id={run.id}" in parts["context_text"]
    assert "Be specific and honest." in parts["context_text"]
    assert long_prompt in parts["context_text"]


def test_get_context_includes_qa_preamble_and_model_settings(db_session):
    tenant = _create_tenant(db_session)
    run, _, _ = _create_run_with_long_step(db_session, tenant)
    db_session.add(
        AiAgentProfile(
            name="Run QA",
            role=RUN_QA_ROLE,
            is_default=True,
            instructions="Be specific and honest.",
            temperature=0.4,
            max_output_tokens=2048,
        )
    )
    db_session.commit()

    context = run_qa_service.get_context(db_session, run)

    assert context["qa_preamble"].startswith("You are answering a staff member's questions about one specific AI agent run")
    assert context["model"] == gemini_client.GEMINI_MODEL
    assert context["temperature"] == 0.4
    assert context["max_output_tokens"] == 2048


def test_answer_question_persists_both_turns_and_grounds_on_context(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    run, long_prompt, long_response = _create_run_with_long_step(db_session, tenant)
    db_session.add(
        AiAgentProfile(
            name="Run QA",
            role=RUN_QA_ROLE,
            is_default=True,
            instructions="Be specific and honest.",
            model="gemini-test-qa",
            temperature=0.25,
            max_output_tokens=321,
        )
    )
    db_session.commit()

    captured_prompt = {}

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompt["prompt"] = prompt
        return gemini_client.GenerationResult(text="It picked template 4.", parsed=None, model="fake", prompt_tokens=1, output_tokens=1, latency_ms=1)

    monkeypatch.setattr(run_qa_service.gemini_client, "generate", fake_generate)

    assistant_message = run_qa_service.answer_question(db_session, run, "What did this run do?", asked_by_user_id=QA_USER.id)
    db_session.commit()

    assert assistant_message.content == "It picked template 4."
    assert assistant_message.qa_run_id is not None
    assert assistant_message.qa_run_id != run.id
    assert long_prompt in captured_prompt["prompt"]
    assert long_response in captured_prompt["prompt"]
    assert "Be specific and honest." in captured_prompt["prompt"]

    messages = db_session.query(RunQaMessage).filter(RunQaMessage.agent_run_id == run.id).order_by(RunQaMessage.id).all()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "What did this run do?"
    assert messages[1].role == "assistant"
    assert messages[1].content == "It picked template 4."
    assert messages[1].qa_run_id == assistant_message.qa_run_id

    qa_run = db_session.query(AiAgentRun).filter(AiAgentRun.id == assistant_message.qa_run_id).one()
    assert qa_run.tenant_id == tenant.id
    assert qa_run.channel == "qa"
    assert qa_run.mode == "manual"
    assert qa_run.status == "completed"
    assert qa_run.total_prompt_tokens == 1
    assert qa_run.total_output_tokens == 1

    step = db_session.query(AiAgentRunStep).filter(AiAgentRunStep.run_id == qa_run.id).one()
    assert step.stage == "qa"
    assert step.prompt == captured_prompt["prompt"]
    assert step.response == "It picked template 4."
    assert step.prompt_tokens == 1
    assert step.output_tokens == 1
    assert step.error is None


def test_answer_question_supports_followup_questions_in_one_session(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    run, _, _ = _create_run_with_long_step(db_session, tenant)
    db_session.add(AiAgentProfile(name="Run QA", role=RUN_QA_ROLE, is_default=True, instructions="Be specific and honest."))
    db_session.commit()

    prompts: list[str] = []
    answers = iter(["First answer.", "Second answer."])

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        prompts.append(prompt)
        return gemini_client.GenerationResult(
            text=next(answers),
            parsed=None,
            model="fake",
            prompt_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    monkeypatch.setattr(run_qa_service.gemini_client, "generate", fake_generate)

    first = run_qa_service.answer_question(db_session, run, "What did this run do?", asked_by_user_id=QA_USER.id)
    second = run_qa_service.answer_question(db_session, run, "And why?", asked_by_user_id=QA_USER.id)
    db_session.commit()

    assert first.content == "First answer."
    assert second.content == "Second answer."
    assert len(prompts) == 2
    assert "## Prior Questions In This Session" in prompts[1]
    assert "Staff: What did this run do?" in prompts[1]
    assert "Assistant: First answer." in prompts[1]

    messages = db_session.query(RunQaMessage).filter(RunQaMessage.agent_run_id == run.id).order_by(RunQaMessage.id).all()
    assert [message.role for message in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1].content == "First answer."
    assert messages[3].content == "Second answer."


def test_answer_question_records_failed_run_when_gemini_errors(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    run, _, _ = _create_run_with_long_step(db_session, tenant)
    db_session.add(AiAgentProfile(name="Run QA", role=RUN_QA_ROLE, is_default=True, instructions="Be specific and honest."))
    db_session.commit()

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        raise gemini_client.GeminiClientError("boom")

    monkeypatch.setattr(run_qa_service.gemini_client, "generate", fake_generate)

    assistant_message = run_qa_service.answer_question(db_session, run, "What did this run do?", asked_by_user_id=QA_USER.id)
    db_session.commit()

    assert assistant_message.content == "Sorry, I couldn't answer that right now - please try again."
    assert assistant_message.qa_run_id is not None

    qa_run = db_session.query(AiAgentRun).filter(AiAgentRun.id == assistant_message.qa_run_id).one()
    assert qa_run.tenant_id == tenant.id
    assert qa_run.channel == "qa"
    assert qa_run.mode == "manual"
    assert qa_run.status == "failed"
    assert qa_run.total_prompt_tokens == 0
    assert qa_run.total_output_tokens == 0

    step = db_session.query(AiAgentRunStep).filter(AiAgentRunStep.run_id == qa_run.id).one()
    assert step.stage == "qa"
    assert step.error == "boom"
    assert step.response is None
    assert step.prompt_tokens is None
    assert step.output_tokens is None


def test_run_qa_endpoints_return_context_and_persist_history(user_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    run, long_prompt, _ = _create_run_with_long_step(db_session, tenant, mode="action_writer")
    db_session.add(
        AiAgentProfile(
            name="Run QA",
            role=RUN_QA_ROLE,
            is_default=True,
            instructions="Be specific and honest.",
            model="gemini-test-qa",
            temperature=0.25,
            max_output_tokens=321,
        )
    )
    db_session.commit()

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(text="It created a task.", parsed=None, model="fake", prompt_tokens=1, output_tokens=1, latency_ms=1)

    monkeypatch.setattr(run_qa_service.gemini_client, "generate", fake_generate)

    context_response = user_client.get(f"/api/ai-agent-runs/{run.id}/qa/context")
    assert context_response.status_code == 200
    context = context_response.json()
    assert f"run_id={run.id}" in context["run_summary"]
    assert "mode=action_writer" in context["run_summary"]
    assert context["instructions"] == "Be specific and honest."
    assert context["qa_preamble"].startswith("You are answering a staff member's questions about one specific AI agent run")
    assert context["model"] == "gemini-test-qa"
    assert context["temperature"] == 0.25
    assert context["max_output_tokens"] == 321
    assert long_prompt in context["run_log_text"]

    ask_response = user_client.post(f"/api/ai-agent-runs/{run.id}/qa", json={"question": "What did this run do?"})
    assert ask_response.status_code == 201
    ask_payload = ask_response.json()
    assert ask_payload["content"] == "It created a task."
    assert ask_payload["qa_run_id"] is not None

    history_response = user_client.get(f"/api/ai-agent-runs/{run.id}/qa")
    assert history_response.status_code == 200
    history = history_response.json()
    roles = [message["role"] for message in history]
    assert roles == ["user", "assistant"]
    assert history[1]["qa_run_id"] == ask_payload["qa_run_id"]


def test_run_qa_context_404_for_missing_run(user_client):
    response = user_client.get("/api/ai-agent-runs/999999/qa/context")
    assert response.status_code == 404
