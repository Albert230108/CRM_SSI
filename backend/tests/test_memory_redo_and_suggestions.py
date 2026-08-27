import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.action_item import ActionItem
from app.models.ai_agent_profile import MEMORY_REDO_ROLE, PLANNER_ROLE, AiAgentProfile
from app.models.ai_agent_run import STATUS_COMPLETED as RUN_STATUS_COMPLETED
from app.models.ai_agent_run import AiAgentRun, AiAgentRunStep
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_reply_template import AiReplyTemplate
from app.models.brain_field_definition import BrainFieldDefinition
from app.models.memory_suggestion import (
    KIND_BRAIN_ENTRY,
    KIND_FIELD_VALUE,
    KIND_PROFILE_CHANGE,
    KIND_RULE_ADD,
    KIND_RULE_DELETE,
    KIND_RULE_MODIFY,
    KIND_TEMPLATE_CHANGE,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    MemorySuggestion,
)
from app.models.tenant import Tenant
from app.models.tenant_brain_entry import TenantBrainEntry
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant_brain_field_value import TenantBrainFieldValue
from app.models.user import User
from app.models.working_memory_rule import STATUS_ACTIVE, WorkingMemoryRule
from app.services import gemini_client, memory_redo_service, memory_suggestion_service

SUGGESTION_USER = User(id=5, email="suggestions@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: SUGGESTION_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Redo Tenant", booking_id="B-redo-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_draft(db_session, tenant, **overrides):
    defaults = dict(tenant_id=tenant.id, channel="whatsapp", generated_text="Hi there!", status="pending")
    defaults.update(overrides)
    draft = AiAutoDraft(**defaults)
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)
    return draft


def _fake_generate(payload):
    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(
            text="ignored", parsed=payload, model=model or "fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    return _generate


def test_propose_updates_returns_empty_without_a_configured_profile(db_session):
    tenant = _create_tenant(db_session)
    draft = _create_draft(db_session, tenant)

    result = memory_redo_service.propose_updates_from_redo(db_session, draft, "make it shorter", None)

    assert result == []


def test_propose_updates_creates_field_value_suggestion(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    draft = _create_draft(db_session, tenant)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    field = BrainFieldDefinition(key="pets", label="Pets", ai_instruction="Does the tenant have pets?")
    db_session.add(field)
    db_session.commit()

    monkeypatch.setattr(
        memory_redo_service.gemini_client,
        "generate",
        _fake_generate(
            {
                "suggestions": [
                    {"kind": KIND_FIELD_VALUE, "field_key": "pets", "value": "Has a cat", "reasoning": "Guest mentioned it durably."}
                ]
            }
        ),
    )

    created = memory_redo_service.propose_updates_from_redo(db_session, draft, "mention the cat policy", "guest has a cat")
    db_session.commit()

    assert len(created) == 1
    suggestion = created[0]
    assert suggestion.kind == KIND_FIELD_VALUE
    assert suggestion.tenant_id == tenant.id
    assert suggestion.target_id == field.id
    assert suggestion.status == STATUS_PENDING


def test_propose_updates_prompt_includes_recent_send_dismiss_reasoning(db_session, monkeypatch):
    """The redo-AGENT (memory_redo) should be able to see why recent drafts for this tenant
    were sent or dismissed, not just fields/entries/rules - see ai_auto_draft.resolution_reason
    and memory_redo_service._recent_decisions_lines."""
    tenant = _create_tenant(db_session)
    draft = _create_draft(db_session, tenant)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    resolved_draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="whatsapp",
        generated_text="Earlier draft",
        status="dismissed",
        resolution_source="human_whatsapp",
        resolution_reason="Guest already confirmed by phone",
    )
    db_session.add(resolved_draft)
    db_session.commit()

    captured_prompts = []

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompts.append(prompt)
        return gemini_client.GenerationResult(
            text="ignored", parsed={"suggestions": []}, model=model or "fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    monkeypatch.setattr(memory_redo_service.gemini_client, "generate", _generate)

    memory_redo_service.propose_updates_from_redo(db_session, draft, "make it shorter", None)
    db_session.commit()

    assert len(captured_prompts) == 1
    assert "Guest already confirmed by phone" in captured_prompts[0]
    assert "dismissed (human_whatsapp)" in captured_prompts[0]

def test_process_redo_prompt_keeps_full_run_log_without_truncation_marker(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    draft = _create_draft(db_session, tenant, agent_run_id=None)
    run = AiAgentRun(tenant_id=tenant.id, channel="crm", mode="manual", status="completed", planner_profile_id=None)
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
    draft.agent_run_id = run.id
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    db_session.commit()

    captured_prompts = []

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompts.append(prompt)
        return gemini_client.GenerationResult(
            text="ignored", parsed={"suggestions": []}, model=model or "fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    monkeypatch.setattr(memory_redo_service.gemini_client, "generate", _generate)

    memory_redo_service.propose_updates_from_redo(db_session, draft, "make it shorter", None)

    assert len(captured_prompts) == 1
    assert long_prompt in captured_prompts[0]
    assert long_response in captured_prompts[0]
    assert "[...truncated]" not in captured_prompts[0]


def test_memory_redo_schema_constrains_kind_to_valid_literals():
    """Regression test for a production bug: an earlier version of MEMORY_REDO_SCHEMA/
    RULE_REDO_SCHEMA left `kind` as an unconstrained string, so Gemini would sometimes emit
    plausible-but-wrong values (e.g. "add_global_rule" instead of "rule_add"). Those got
    silently dropped in _create_suggestions - the AiAgentRun still logged "completed" with
    real-looking suggestions in its parsed output, but zero MemorySuggestion rows were ever
    created, so nothing ever appeared in Pending Suggestions. The enum is what actually
    prevents the model from emitting anything else.
    """
    kind_schema = memory_redo_service.MEMORY_REDO_SCHEMA["properties"]["suggestions"]["items"]["properties"]["kind"]
    assert set(kind_schema["enum"]) == {
        KIND_FIELD_VALUE,
        KIND_BRAIN_ENTRY,
        KIND_RULE_ADD,
        KIND_RULE_MODIFY,
        KIND_RULE_DELETE,
        KIND_PROFILE_CHANGE,
        KIND_TEMPLATE_CHANGE,
    }

    rule_kind_schema = memory_redo_service.RULE_REDO_SCHEMA["properties"]["suggestions"]["items"]["properties"]["kind"]
    assert set(rule_kind_schema["enum"]) == {
        KIND_RULE_ADD,
        KIND_RULE_MODIFY,
        KIND_RULE_DELETE,
        KIND_PROFILE_CHANGE,
        KIND_TEMPLATE_CHANGE,
    }


def test_propose_updates_logs_and_skips_unrecognized_kind(db_session, monkeypatch, caplog):
    tenant = _create_tenant(db_session)
    draft = _create_draft(db_session, tenant)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    db_session.commit()

    monkeypatch.setattr(
        memory_redo_service.gemini_client,
        "generate",
        _fake_generate(
            {"suggestions": [{"kind": "add_global_rule", "condition_text": "x", "action_text": "y", "reasoning": "z"}]}
        ),
    )

    with caplog.at_level("WARNING"):
        created = memory_redo_service.propose_updates_from_redo(db_session, draft, "make it shorter", None)
    db_session.commit()

    assert created == []
    assert db_session.query(MemorySuggestion).count() == 0
    assert any("unrecognized kind" in record.message for record in caplog.records)


def test_propose_updates_ignores_hallucinated_field_key(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    draft = _create_draft(db_session, tenant)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    db_session.commit()

    monkeypatch.setattr(
        memory_redo_service.gemini_client,
        "generate",
        _fake_generate({"suggestions": [{"kind": KIND_FIELD_VALUE, "field_key": "does_not_exist", "value": "x", "reasoning": "r"}]}),
    )

    created = memory_redo_service.propose_updates_from_redo(db_session, draft, "x", None)

    assert created == []


def test_propose_updates_creates_rule_add_suggestion_with_null_tenant(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    draft = _create_draft(db_session, tenant)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    db_session.commit()

    monkeypatch.setattr(
        memory_redo_service.gemini_client,
        "generate",
        _fake_generate(
            {
                "suggestions": [
                    {
                        "kind": KIND_RULE_ADD,
                        "condition_text": "Returning customer",
                        "action_text": "Always offer a discount",
                        "reasoning": "Staff explicitly asked for this every time.",
                    }
                ]
            }
        ),
    )

    created = memory_redo_service.propose_updates_from_redo(db_session, draft, "offer discount", "they're a returning guest")
    db_session.commit()

    assert len(created) == 1
    assert created[0].kind == KIND_RULE_ADD
    assert created[0].tenant_id is None


# --- memory_suggestion_service.approve/reject -----------------------------------------------


def test_approve_field_value_suggestion_writes_value(db_session):
    tenant = _create_tenant(db_session)
    field = BrainFieldDefinition(key="pets", label="Pets", ai_instruction="?")
    db_session.add(field)
    db_session.commit()
    suggestion = MemorySuggestion(
        kind=KIND_FIELD_VALUE, tenant_id=tenant.id, target_id=field.id, proposed_value={"field_key": "pets", "value": "Has a dog"}, status=STATUS_PENDING
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion, reviewer_id=SUGGESTION_USER.id)
    db_session.commit()

    assert result.applied is True
    assert suggestion.status == STATUS_APPROVED
    value = db_session.query(TenantBrainFieldValue).filter(TenantBrainFieldValue.tenant_id == tenant.id).one()
    assert value.value == "Has a dog"


def test_approve_field_value_suggestion_rejects_when_field_deactivated(db_session):
    tenant = _create_tenant(db_session)
    field = BrainFieldDefinition(key="pets", label="Pets", ai_instruction="?", is_active=False)
    db_session.add(field)
    db_session.commit()
    suggestion = MemorySuggestion(
        kind=KIND_FIELD_VALUE, tenant_id=tenant.id, target_id=field.id, proposed_value={"field_key": "pets", "value": "Has a dog"}, status=STATUS_PENDING
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion)
    db_session.commit()

    assert result.applied is False
    assert suggestion.status == STATUS_REJECTED
    assert db_session.query(TenantBrainFieldValue).count() == 0


def test_approve_brain_entry_suggestion_adds_entry(db_session):
    tenant = _create_tenant(db_session)
    suggestion = MemorySuggestion(kind=KIND_BRAIN_ENTRY, tenant_id=tenant.id, proposed_value={"content": "Prefers quiet rooms"}, status=STATUS_PENDING)
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion)
    db_session.commit()

    assert result.applied is True
    entry = db_session.query(TenantBrainEntry).filter(TenantBrainEntry.tenant_id == tenant.id).one()
    assert entry.content == "Prefers quiet rooms"
    assert entry.source == "planner"


def test_approve_rule_add_suggestion_creates_active_rule(db_session):
    suggestion = MemorySuggestion(
        kind=KIND_RULE_ADD, tenant_id=None, proposed_value={"condition_text": "Returning customer", "action_text": "Offer a discount"}, status=STATUS_PENDING
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion)
    db_session.commit()

    assert result.applied is True
    rule = db_session.query(WorkingMemoryRule).one()
    assert rule.status == STATUS_ACTIVE
    assert rule.source == "ai_suggested"


def test_approve_rule_modify_suggestion_rejects_when_rule_already_dismissed(db_session):
    rule = WorkingMemoryRule(condition_text="X", action_text="Y", status="dismissed", source="manual")
    db_session.add(rule)
    db_session.commit()
    suggestion = MemorySuggestion(
        kind=KIND_RULE_MODIFY, target_id=rule.id, proposed_value={"rule_id": rule.id, "condition_text": "Z", "action_text": None}, status=STATUS_PENDING
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion)
    db_session.commit()

    assert result.applied is False
    assert suggestion.status == STATUS_REJECTED
    db_session.refresh(rule)
    assert rule.condition_text == "X"


def test_approve_rule_delete_suggestion_dismisses_rule(db_session):
    rule = WorkingMemoryRule(condition_text="X", action_text="Y", status=STATUS_ACTIVE, source="manual")
    db_session.add(rule)
    db_session.commit()
    suggestion = MemorySuggestion(kind=KIND_RULE_DELETE, target_id=rule.id, proposed_value={"rule_id": rule.id}, status=STATUS_PENDING)
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion)
    db_session.commit()

    assert result.applied is True
    db_session.refresh(rule)
    assert rule.status == "dismissed"


def test_reject_marks_suggestion_rejected_without_applying(db_session):
    tenant = _create_tenant(db_session)
    suggestion = MemorySuggestion(kind=KIND_BRAIN_ENTRY, tenant_id=tenant.id, proposed_value={"content": "x"}, status=STATUS_PENDING)
    db_session.add(suggestion)
    db_session.commit()

    memory_suggestion_service.reject(db_session, suggestion, reviewer_id=SUGGESTION_USER.id)
    db_session.commit()

    assert suggestion.status == STATUS_REJECTED
    assert db_session.query(TenantBrainEntry).count() == 0


def test_approve_endpoint_rejects_already_reviewed_suggestion(user_client, db_session):
    tenant = _create_tenant(db_session)
    suggestion = MemorySuggestion(kind=KIND_BRAIN_ENTRY, tenant_id=tenant.id, proposed_value={"content": "x"}, status=STATUS_APPROVED)
    db_session.add(suggestion)
    db_session.commit()

    response = user_client.post(f"/api/memory-suggestions/{suggestion.id}/approve")

    assert response.status_code == 409


def test_process_redo_request_log_creates_rule_suggestion_and_marks_processed(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    db_session.commit()

    log_entry = RedoRequestLog(tenant_id=tenant.id, channel="crm", what="make this more flexible", why="guest may change dates")
    db_session.add(log_entry)
    db_session.commit()
    db_session.refresh(log_entry)

    monkeypatch.setattr(
        memory_redo_service.gemini_client,
        "generate",
        _fake_generate(
            {
                "suggestions": [
                    {
                        "kind": KIND_RULE_ADD,
                        "condition_text": "Guest asks to reschedule",
                        "action_text": "Offer one flexible date change",
                        "reasoning": "This is a durable policy tweak.",
                    }
                ]
            }
        ),
    )

    created = memory_redo_service.process_redo_request_log(db_session, log_entry.id)
    db_session.commit()

    assert len(created) == 1
    db_session.refresh(log_entry)
    assert log_entry.processed_at is not None
    assert log_entry.memory_redo_run_id is not None
    suggestion = created[0]
    assert suggestion.kind == KIND_RULE_ADD
    assert suggestion.source_redo_log_id == log_entry.id


# --- full run log wired into the redo prompt ------------------------------------------------


def _create_run_with_steps(db_session, tenant, *, planner_profile_id=None, final_template_id=None):
    run = AiAgentRun(
        tenant_id=tenant.id,
        channel="whatsapp",
        mode="manual",
        status=RUN_STATUS_COMPLETED,
        planner_profile_id=planner_profile_id,
        final_template_id=final_template_id,
        final_text="Hi there!",
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    db_session.add(
        AiAgentRunStep(
            run_id=run.id,
            step_index=0,
            stage="planner",
            model="fake-model",
            prompt="planner prompt text",
            response="planner response text",
        )
    )
    db_session.commit()
    return run


def test_propose_updates_from_redo_includes_full_run_log_when_draft_has_a_run(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    planner_profile = AiAgentProfile(name="Planner", role=PLANNER_ROLE, is_default=True)
    db_session.add(planner_profile)
    db_session.commit()
    db_session.refresh(planner_profile)

    run = _create_run_with_steps(db_session, tenant, planner_profile_id=planner_profile.id)
    draft = _create_draft(db_session, tenant, agent_run_id=run.id)

    captured_prompts = []

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompts.append(prompt)
        return gemini_client.GenerationResult(
            text="ignored", parsed={"suggestions": []}, model=model or "fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    monkeypatch.setattr(memory_redo_service.gemini_client, "generate", _generate)

    memory_redo_service.propose_updates_from_redo(db_session, draft, "make it shorter", None)
    db_session.commit()

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert f"run_id={run.id}" in prompt
    assert f"planner_profile_id={planner_profile.id}" in prompt
    assert "planner prompt text" in prompt
    assert "planner response text" in prompt


def test_process_redo_request_log_includes_run_log_via_ai_agent_run_id(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    db_session.commit()

    run = _create_run_with_steps(db_session, tenant)
    log_entry = RedoRequestLog(tenant_id=tenant.id, channel="crm", what="make this shorter", ai_agent_run_id=run.id)
    db_session.add(log_entry)
    db_session.commit()
    db_session.refresh(log_entry)

    captured_prompts = []

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompts.append(prompt)
        return gemini_client.GenerationResult(
            text="ignored", parsed={"suggestions": []}, model=model or "fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    monkeypatch.setattr(memory_redo_service.gemini_client, "generate", _generate)

    memory_redo_service.process_redo_request_log(db_session, log_entry.id)
    db_session.commit()

    assert len(captured_prompts) == 1
    assert f"run_id={run.id}" in captured_prompts[0]
    assert "planner prompt text" in captured_prompts[0]


def test_process_redo_request_log_resolves_run_log_via_linked_auto_draft(db_session, monkeypatch):
    """RedoRequestLog only stores ai_agent_run_id directly for the reply-box path - the
    AiAutoDraft approval-flow path leaves it null and instead links via ai_auto_draft_id, so the
    run log must be resolved through AiAutoDraft.agent_run_id in that case."""
    tenant = _create_tenant(db_session)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    db_session.commit()

    run = _create_run_with_steps(db_session, tenant)
    draft = _create_draft(db_session, tenant, agent_run_id=run.id)
    log_entry = RedoRequestLog(tenant_id=tenant.id, channel="whatsapp", what="make this shorter", ai_auto_draft_id=draft.id)
    db_session.add(log_entry)
    db_session.commit()
    db_session.refresh(log_entry)

    captured_prompts = []

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompts.append(prompt)
        return gemini_client.GenerationResult(
            text="ignored", parsed={"suggestions": []}, model=model or "fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    monkeypatch.setattr(memory_redo_service.gemini_client, "generate", _generate)

    memory_redo_service.process_redo_request_log(db_session, log_entry.id)
    db_session.commit()

    assert len(captured_prompts) == 1
    assert f"run_id={run.id}" in captured_prompts[0]


# --- profile_change / template_change suggestions -------------------------------------------


def test_process_redo_request_log_creates_profile_change_suggestion(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    planner_profile = AiAgentProfile(name="Planner", role=PLANNER_ROLE, is_default=True)
    db_session.add(planner_profile)
    db_session.commit()
    db_session.refresh(planner_profile)

    run = _create_run_with_steps(db_session, tenant, planner_profile_id=planner_profile.id)
    log_entry = RedoRequestLog(tenant_id=tenant.id, channel="crm", what="stop offering discounts unprompted", ai_agent_run_id=run.id)
    db_session.add(log_entry)
    db_session.commit()
    db_session.refresh(log_entry)

    monkeypatch.setattr(
        memory_redo_service.gemini_client,
        "generate",
        _fake_generate(
            {
                "suggestions": [
                    {
                        "kind": KIND_PROFILE_CHANGE,
                        "profile_id": planner_profile.id,
                        "field": "instructions",
                        "suggested_text": "Never offer a discount unless the guest asks first.",
                        "reasoning": "The planner's own instructions caused the unwanted offer, per the run log.",
                    }
                ]
            }
        ),
    )

    created = memory_redo_service.process_redo_request_log(db_session, log_entry.id)
    db_session.commit()

    assert len(created) == 1
    suggestion = created[0]
    assert suggestion.kind == KIND_PROFILE_CHANGE
    assert suggestion.tenant_id is None
    assert suggestion.target_id == planner_profile.id
    assert suggestion.proposed_value == {
        "profile_id": planner_profile.id,
        "field": "instructions",
        "suggested_text": "Never offer a discount unless the guest asks first.",
    }


def test_process_redo_request_log_creates_template_change_suggestion(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    template = AiReplyTemplate(name="Booking Confirmation", guidelines="Confirm the dates.", created_by_user_id=1)
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    run = _create_run_with_steps(db_session, tenant, final_template_id=template.id)
    log_entry = RedoRequestLog(tenant_id=tenant.id, channel="crm", what="the confirmation is missing the checkout time", ai_agent_run_id=run.id)
    db_session.add(log_entry)
    db_session.commit()
    db_session.refresh(log_entry)

    monkeypatch.setattr(
        memory_redo_service.gemini_client,
        "generate",
        _fake_generate(
            {
                "suggestions": [
                    {
                        "kind": KIND_TEMPLATE_CHANGE,
                        "template_id": template.id,
                        "field": "guidelines",
                        "suggested_text": "Confirm the dates and always state the checkout time.",
                        "reasoning": "This template's guidelines never mention checkout time.",
                    }
                ]
            }
        ),
    )

    created = memory_redo_service.process_redo_request_log(db_session, log_entry.id)
    db_session.commit()

    assert len(created) == 1
    suggestion = created[0]
    assert suggestion.kind == KIND_TEMPLATE_CHANGE
    assert suggestion.tenant_id is None
    assert suggestion.target_id == template.id
    assert suggestion.proposed_value["section_id"] is None


def test_process_redo_request_log_creates_template_change_suggestion_with_section_id(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    template = AiReplyTemplate(
        name="Booking Confirmation",
        guidelines="Confirm the dates.",
        sections=[{"id": "sec-1", "label": "Checkout Info", "content": "Checkout is at 11am.", "x": 0, "y": 0, "order": 0}],
        created_by_user_id=1,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    run = _create_run_with_steps(db_session, tenant, final_template_id=template.id)
    log_entry = RedoRequestLog(tenant_id=tenant.id, channel="crm", what="the confirmation is missing the checkout time", ai_agent_run_id=run.id)
    db_session.add(log_entry)
    db_session.commit()
    db_session.refresh(log_entry)

    captured_prompts = []

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompts.append(prompt)
        return gemini_client.GenerationResult(
            text="ignored",
            parsed={
                "suggestions": [
                    {
                        "kind": KIND_TEMPLATE_CHANGE,
                        "template_id": template.id,
                        "field": "sections",
                        "section_id": "sec-1",
                        "suggested_text": "Checkout is at 11am. Always state this.",
                        "reasoning": "The Checkout Info section never mentions the checkout time explicitly.",
                    }
                ]
            },
            model=model or "fake-model",
            prompt_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    monkeypatch.setattr(memory_redo_service.gemini_client, "generate", _generate)

    created = memory_redo_service.process_redo_request_log(db_session, log_entry.id)
    db_session.commit()

    assert len(captured_prompts) == 1
    assert "section_id=sec-1" in captured_prompts[0]
    assert "Checkout Info" in captured_prompts[0]

    assert len(created) == 1
    suggestion = created[0]
    assert suggestion.kind == KIND_TEMPLATE_CHANGE
    assert suggestion.target_id == template.id
    assert suggestion.proposed_value["section_id"] == "sec-1"


def test_process_redo_request_log_drops_template_change_with_unknown_section_id(db_session, monkeypatch, caplog):
    """Regression guard mirroring test_propose_updates_ignores_hallucinated_field_key: a
    section_id the model invents (not present in the template's real sections) must never
    become a suggestion a human reviews as if it pointed at a real block."""
    tenant = _create_tenant(db_session)
    db_session.add(AiAgentProfile(name="Memory Redo", role=MEMORY_REDO_ROLE, is_default=True))
    template = AiReplyTemplate(
        name="Booking Confirmation",
        guidelines="Confirm the dates.",
        sections=[{"id": "sec-1", "label": "Checkout Info", "content": "Checkout is at 11am.", "x": 0, "y": 0, "order": 0}],
        created_by_user_id=1,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    run = _create_run_with_steps(db_session, tenant, final_template_id=template.id)
    log_entry = RedoRequestLog(tenant_id=tenant.id, channel="crm", what="the confirmation is missing the checkout time", ai_agent_run_id=run.id)
    db_session.add(log_entry)
    db_session.commit()
    db_session.refresh(log_entry)

    monkeypatch.setattr(
        memory_redo_service.gemini_client,
        "generate",
        _fake_generate(
            {
                "suggestions": [
                    {
                        "kind": KIND_TEMPLATE_CHANGE,
                        "template_id": template.id,
                        "field": "sections",
                        "section_id": "sec-does-not-exist",
                        "suggested_text": "x",
                        "reasoning": "y",
                    }
                ]
            }
        ),
    )

    with caplog.at_level("WARNING"):
        created = memory_redo_service.process_redo_request_log(db_session, log_entry.id)
    db_session.commit()

    assert created == []
    assert db_session.query(MemorySuggestion).count() == 0
    assert any("unknown section_id" in record.message for record in caplog.records)


def test_approve_profile_change_suggestion_does_not_mutate_profile(db_session):
    """profile_change/template_change are suggestion-only: approving records human review but
    must never rewrite the profile - a human edits it by hand in the Agent Profiles editor."""
    profile = AiAgentProfile(name="Planner", role=PLANNER_ROLE, instructions="Original instructions.")
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)

    suggestion = MemorySuggestion(
        kind=KIND_PROFILE_CHANGE,
        tenant_id=None,
        target_id=profile.id,
        proposed_value={"profile_id": profile.id, "field": "instructions", "suggested_text": "New instructions."},
        status=STATUS_PENDING,
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion, reviewer_id=SUGGESTION_USER.id)
    db_session.commit()

    assert result.applied is True
    assert suggestion.status == STATUS_APPROVED
    db_session.refresh(profile)
    assert profile.instructions == "Original instructions."


def test_approve_profile_change_suggestion_rejects_when_profile_deleted(db_session):
    suggestion = MemorySuggestion(
        kind=KIND_PROFILE_CHANGE,
        tenant_id=None,
        target_id=999999,
        proposed_value={"profile_id": 999999, "field": "instructions", "suggested_text": "New instructions."},
        status=STATUS_PENDING,
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion)
    db_session.commit()

    assert result.applied is False
    assert suggestion.status == STATUS_REJECTED


def test_approve_template_change_suggestion_does_not_mutate_template(db_session):
    template = AiReplyTemplate(name="Booking Confirmation", guidelines="Original guidelines.", created_by_user_id=1)
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    suggestion = MemorySuggestion(
        kind=KIND_TEMPLATE_CHANGE,
        tenant_id=None,
        target_id=template.id,
        proposed_value={"template_id": template.id, "field": "guidelines", "suggested_text": "New guidelines."},
        status=STATUS_PENDING,
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion, reviewer_id=SUGGESTION_USER.id)
    db_session.commit()

    assert result.applied is True
    assert suggestion.status == STATUS_APPROVED
    db_session.refresh(template)
    assert template.guidelines == "Original guidelines."
