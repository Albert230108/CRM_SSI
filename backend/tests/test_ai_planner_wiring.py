"""Covers how the planner loop plugs into the existing auto-draft pipeline and reply box."""
import json
from datetime import datetime, timezone

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.ai_agent_profile import AiAgentProfile
from app.models.ai_agent_run import AiAgentRun
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.ai_reply_template import AiReplyTemplate
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.user import User
from app.services import ai_agent_orchestrator, ai_auto_draft_service, gemini_client

REGULAR_USER = User(id=2, email="agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _fake_generate(responses):
    queue = list(responses)

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        payload = queue.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return gemini_client.GenerationResult(
            text=payload if isinstance(payload, str) else json.dumps(payload),
            parsed=payload if isinstance(payload, dict) else None,
            model=model or "fake-model",
            prompt_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    return _generate


def _setup(db_session, *, planner_mode="auto-send", auto_send=False, max_redraft_attempts=1):
    tenant = Tenant(name="Wired Tenant", booking_id="B-wire-1")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    template = AiReplyTemplate(
        name="Late check-in",
        description="Use for late arrivals.",
        sections=[{"label": "Persona", "content": "Be helpful."}],
        created_by_user_id=1,
    )
    db_session.add(template)
    db_session.add(AiAgentProfile(name="P", role="planner", is_default=True, escalate_keywords=[]))
    db_session.add(
        AiAgentProfile(
            name="C",
            role="checker",
            is_default=True,
            escalate_keywords=[],
            max_redraft_attempts=max_redraft_attempts,
        )
    )
    db_session.add(
        TenantAiSettings(
            tenant_id=tenant.id,
            planner_mode=planner_mode,
            auto_draft_email=True,
            auto_send_email=auto_send,
        )
    )
    db_session.commit()
    db_session.refresh(template)
    return tenant, template


def _plan(template_id, **overrides):
    payload = {
        "should_reply": True,
        "template_id": template_id,
        "extra_brain_sections": [],
        "extra_instructions": "Confirm the arrival time.",
        "confidence": 0.9,
        "reasoning": "Guest asked about arrival.",
        "alternatives": [],
    }
    payload.update(overrides)
    return payload


def test_auto_mode_uses_the_planner_instead_of_the_default_template(db_session, monkeypatch):
    tenant, template = _setup(db_session)
    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Auto draft.", {"passed": True, "feedback": ""}]),
    )
    trigger = AiAutoDraftTrigger(
        tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc)
    )

    draft = ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger)
    db_session.commit()

    assert draft is not None
    assert draft.generated_text == "Auto draft."
    assert draft.template_id == template.id
    assert draft.status == "pending"
    assert draft.agent_run_id is not None
    assert db_session.query(AiAgentRun).filter(AiAgentRun.id == draft.agent_run_id).one().mode == "auto-send"


def test_auto_send_is_scheduled_only_when_the_checker_approved(db_session, monkeypatch):
    tenant, template = _setup(db_session, auto_send=True)
    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Approved draft.", {"passed": True, "feedback": ""}]),
    )
    trigger = AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    draft = ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger)
    db_session.commit()

    assert draft.status == "pending_auto_send"
    assert draft.scheduled_send_at is not None


def test_auto_draft_mode_never_schedules_an_auto_send(db_session, monkeypatch):
    """Regression: auto-draft must land in the AI Drafts tab, never in the auto-send queue,
    even when the tenant's auto_send toggle is on and the checker approved the draft."""
    tenant, template = _setup(db_session, planner_mode="auto-draft", auto_send=True)
    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Approved draft.", {"passed": True, "feedback": ""}]),
    )
    trigger = AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    draft = ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger)
    db_session.commit()

    assert draft.status == "pending"
    assert draft.scheduled_send_at is None
    assert draft.agent_run_id is not None
    assert db_session.query(AiAgentRun).filter(AiAgentRun.id == draft.agent_run_id).one().mode == "auto-draft"


def test_rejected_draft_is_parked_and_never_auto_sent(db_session, monkeypatch):
    tenant, template = _setup(db_session, auto_send=True, max_redraft_attempts=0)
    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Bad draft.", {"passed": False, "feedback": "Wrong tone."}]),
    )
    trigger = AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    draft = ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger)
    db_session.commit()

    assert draft.status == "needs_review"
    assert draft.checker_feedback == "Wrong tone."
    # The auto-send sweep only ever picks up "pending_auto_send", so a parked draft cannot go out.
    assert draft.scheduled_send_at is None
    assert (
        db_session.query(AiAutoDraft)
        .filter(AiAutoDraft.status == "pending_auto_send", AiAutoDraft.tenant_id == tenant.id)
        .count()
        == 0
    )


def test_planner_declining_produces_no_draft_row(db_session, monkeypatch):
    tenant, template = _setup(db_session)
    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id, should_reply=False)]),
    )
    trigger = AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    assert ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger) is None
    db_session.commit()
    assert db_session.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant.id).count() == 0
    # The decision is still logged - "why didn't it reply?" must be answerable.
    run = db_session.query(AiAgentRun).filter(AiAgentRun.tenant_id == tenant.id).one()
    assert run.status == "skipped"


def test_planner_mode_off_keeps_the_existing_default_template_path(db_session, monkeypatch):
    """Regression guard: tenants that never opt in must behave exactly as before."""
    tenant, template = _setup(db_session, planner_mode="off")
    settings = db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).one()
    settings.default_email_template_id = template.id
    db_session.commit()

    def _boom(*args, **kwargs):
        raise AssertionError("The planner must not run when planner_mode is off")

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", _boom)
    monkeypatch.setattr(
        ai_auto_draft_service.ai_reply_service.gemini_client,
        "generate_text_flat",
        lambda prompt: "Legacy draft.",
    )
    trigger = AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    draft = ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger)
    db_session.commit()

    assert draft.generated_text == "Legacy draft."
    assert draft.agent_run_id is None


def test_manual_ai_plan_endpoint_returns_the_final_text(user_client, db_session, monkeypatch):
    tenant, template = _setup(db_session, planner_mode="manual")
    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Manual draft.", {"passed": True, "feedback": ""}]),
    )

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-plan",
        json={"channel": "email", "rough_draft": "Mention the lockbox."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generated_text"] == "Manual draft."
    assert body["status"] == "completed"
    assert body["checker_passed"] is True
    assert body["template_id"] == template.id
    assert db_session.query(AiAgentRun).filter(AiAgentRun.id == body["run_id"]).one().mode == "manual"


def test_ai_plan_is_refused_when_the_planner_is_off(user_client, db_session):
    tenant, _ = _setup(db_session, planner_mode="off")
    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-plan", json={"channel": "email"}
    )
    assert response.status_code == 400
    assert "turned off" in response.json()["detail"]


def test_ai_plan_rejects_an_unknown_channel(user_client, db_session):
    tenant, _ = _setup(db_session, planner_mode="manual")
    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-plan", json={"channel": "carrier-pigeon"}
    )
    assert response.status_code == 400


def test_ai_plan_maps_gemini_failure_to_502(user_client, db_session, monkeypatch):
    tenant, _ = _setup(db_session, planner_mode="manual")

    def _raise(*args, **kwargs):
        raise gemini_client.GeminiClientError("GEMINI_API_KEY is not configured")

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", _raise)

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-plan", json={"channel": "email"}
    )
    assert response.status_code == 502


def test_runs_api_exposes_the_planner_decision(client, db_session, monkeypatch):
    tenant, template = _setup(db_session, planner_mode="manual")
    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}]),
    )
    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Hi"
    )
    db_session.commit()

    listing = client.get("/api/ai-agent-runs").json()
    assert [run["id"] for run in listing] == [result.run_id]
    assert listing[0]["tenant_name"] == "Wired Tenant"
    assert listing[0]["final_template_name"] == "Late check-in"

    detail = client.get(f"/api/ai-agent-runs/{result.run_id}").json()
    assert [step["stage"] for step in detail["steps"]] == ["planner", "drafter", "checker"]
    assert detail["steps"][0]["parsed"]["reasoning"] == "Guest asked about arrival."
    assert detail["final_text"] == "Draft."
    assert detail["final_template_name"] == "Late check-in"
    assert detail["template_names"] == {str(template.id): "Late check-in"}


def test_runs_api_resolves_names_for_rejected_alternatives(client, db_session, monkeypatch):
    """Regression: the planner log used to show only raw template ids, never names."""
    tenant, template = _setup(db_session, planner_mode="manual")
    other_template = AiReplyTemplate(
        name="Early check-in",
        sections=[{"label": "Persona", "content": "Be helpful."}],
        created_by_user_id=1,
    )
    db_session.add(other_template)
    db_session.commit()
    db_session.refresh(other_template)

    plan = _plan(
        template.id,
        alternatives=[{"template_id": other_template.id, "why_not": "Guest already checked in."}],
    )
    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([plan, "Draft.", {"passed": True, "feedback": ""}]),
    )
    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Hi"
    )
    db_session.commit()

    detail = client.get(f"/api/ai-agent-runs/{result.run_id}").json()
    assert detail["template_names"] == {
        str(template.id): "Late check-in",
        str(other_template.id): "Early check-in",
    }


def test_runs_api_filters_by_status(client, db_session):
    tenant = Tenant(name="Filter Tenant", booking_id="B-filter-1")
    db_session.add(tenant)
    db_session.commit()
    db_session.add(AiAgentRun(tenant_id=tenant.id, channel="email", mode="auto", status="completed"))
    db_session.add(AiAgentRun(tenant_id=tenant.id, channel="email", mode="auto", status="needs_review"))
    db_session.commit()

    assert len(client.get("/api/ai-agent-runs?status=needs_review").json()) == 1
    assert len(client.get(f"/api/ai-agent-runs?tenant_id={tenant.id}").json()) == 2


def _step_prompt(db_session, run_id, stage):
    from app.models.ai_agent_run import AiAgentRunStep

    step = (
        db_session.query(AiAgentRunStep)
        .filter(AiAgentRunStep.run_id == run_id, AiAgentRunStep.stage == stage)
        .order_by(AiAgentRunStep.step_index)
        .first()
    )
    assert step is not None, f"no {stage} step recorded for run {run_id}"
    return step.prompt


def test_planner_prompt_reproduces_the_built_in_wording_by_default(db_session, monkeypatch):
    """Regression: a profile with no prompt_blocks overrides must produce exactly the wording
    that used to be hardcoded, so this change is a no-op for every profile created before it."""
    from app.services import ai_prompt_blocks

    tenant, template = _setup(db_session, planner_mode="manual")
    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}]),
    )

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="When can I check in?"
    )
    db_session.commit()

    planner_prompt = _step_prompt(db_session, result.run_id, "planner")
    defaults = ai_prompt_blocks.DEFAULTS_BY_ROLE["planner"]
    assert defaults["preamble"] in planner_prompt
    assert defaults["language"] in planner_prompt
    assert "Pick `template_id` from this list only." in planner_prompt
    assert defaults["output"] in planner_prompt

    checker_prompt = _step_prompt(db_session, result.run_id, "checker")
    checker_defaults = ai_prompt_blocks.DEFAULTS_BY_ROLE["checker"]
    assert checker_defaults["preamble"] in checker_prompt
    assert checker_defaults["output"] in checker_prompt


def test_planner_preamble_override_replaces_the_default_wording(db_session, monkeypatch):
    tenant, template = _setup(db_session, planner_mode="manual")
    profile = db_session.query(AiAgentProfile).filter(AiAgentProfile.role == "planner").one()
    profile.prompt_blocks = {"preamble": "Custom planner preamble."}
    db_session.commit()

    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}]),
    )
    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Hi"
    )
    db_session.commit()

    planner_prompt = _step_prompt(db_session, result.run_id, "planner")
    assert "Custom planner preamble." in planner_prompt
    assert "You are the planner for a short-stay rental CRM" not in planner_prompt


def test_clearing_the_operator_note_block_removes_the_framing_but_keeps_the_text(db_session, monkeypatch):
    tenant, template = _setup(db_session, planner_mode="manual")
    profile = db_session.query(AiAgentProfile).filter(AiAgentProfile.role == "planner").one()
    profile.prompt_blocks = {"operator_note": ""}
    db_session.commit()

    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}]),
    )
    result = ai_agent_orchestrator.run_planner_loop(
        db_session,
        tenant=tenant,
        channel="email",
        mode="manual",
        inbound_text="Hi",
        operator_note="Guest wants an early check-in.",
    )
    db_session.commit()

    planner_prompt = _step_prompt(db_session, result.run_id, "planner")
    assert "## Operator Note" not in planner_prompt
    assert "Guest wants an early check-in." in planner_prompt


def test_clearing_the_language_rule_stops_it_being_sent(db_session, monkeypatch):
    tenant, template = _setup(db_session, planner_mode="manual")
    profile = db_session.query(AiAgentProfile).filter(AiAgentProfile.role == "planner").one()
    profile.prompt_blocks = {"language": ""}
    db_session.commit()

    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}]),
    )
    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Hi"
    )
    db_session.commit()

    planner_prompt = _step_prompt(db_session, result.run_id, "planner")
    assert "same language the guest used" not in planner_prompt


def test_drafter_profile_overrides_the_section_label_in_the_planner_loop(db_session, monkeypatch):
    tenant, template = _setup(db_session, planner_mode="manual")
    drafter = AiAgentProfile(
        name="D", role="drafter", is_default=True, escalate_keywords=[],
        prompt_blocks={"sections": "Custom Drafter Section"},
    )
    db_session.add(drafter)
    db_session.commit()

    monkeypatch.setattr(
        ai_agent_orchestrator.gemini_client,
        "generate",
        _fake_generate([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}]),
    )
    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Hi"
    )
    db_session.commit()

    drafter_prompt = _step_prompt(db_session, result.run_id, "drafter")
    assert "Custom Drafter Section" in drafter_prompt
    assert "1. Template Text" not in drafter_prompt


def test_resolve_drafter_context_returns_built_in_defaults_with_no_pinned_profile(db_session):
    blocks, instructions = ai_agent_orchestrator.resolve_drafter_context(db_session, None)
    from app.services import ai_prompt_blocks

    assert blocks == ai_prompt_blocks.DEFAULTS_BY_ROLE["drafter"]
    assert instructions is None
