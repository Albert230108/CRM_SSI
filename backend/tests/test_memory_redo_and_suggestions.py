import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.action_item import ActionItem
from app.models.ai_agent_profile import MEMORY_REDO_ROLE, AiAgentProfile
from app.models.ai_auto_draft import AiAutoDraft
from app.models.brain_field_definition import BrainFieldDefinition
from app.models.memory_suggestion import (
    KIND_BRAIN_ENTRY,
    KIND_FIELD_VALUE,
    KIND_RULE_ADD,
    KIND_RULE_DELETE,
    KIND_RULE_MODIFY,
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
