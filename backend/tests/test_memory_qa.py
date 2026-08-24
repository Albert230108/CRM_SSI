import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.action_item import ActionItem
from app.models.brain_field_definition import BrainFieldDefinition
from app.models.memory_qa_message import MemoryQaMessage
from app.models.tenant import Tenant
from app.models.tenant_brain_field_value import TenantBrainFieldValue
from app.models.user import User
from app.services import gemini_client, memory_qa_service

QA_USER = User(id=6, email="qa@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: QA_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _create_tenant(db_session, **overrides):
    defaults = dict(name="QA Tenant", booking_id="B-qa-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_answer_question_persists_both_turns_and_grounds_on_context(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    field = BrainFieldDefinition(key="pets", label="Pets", ai_instruction="?")
    db_session.add(field)
    db_session.commit()
    db_session.add(TenantBrainFieldValue(tenant_id=tenant.id, field_definition_id=field.id, value="Has a dog", source="manual"))
    db_session.add(ActionItem(tenant_id=tenant.id, title="Call about invoice", status="open", source="manual"))
    db_session.commit()

    captured_prompt = {}

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompt["prompt"] = prompt
        return gemini_client.GenerationResult(text="The tenant has a dog.", parsed=None, model="fake", prompt_tokens=1, output_tokens=1, latency_ms=1)

    monkeypatch.setattr(memory_qa_service.gemini_client, "generate", fake_generate)

    assistant_message = memory_qa_service.answer_question(db_session, tenant, "Does this tenant have pets?", asked_by_user_id=QA_USER.id)
    db_session.commit()

    assert assistant_message.content == "The tenant has a dog."
    assert "Has a dog" in captured_prompt["prompt"]
    assert "Call about invoice" in captured_prompt["prompt"]

    messages = db_session.query(MemoryQaMessage).filter(MemoryQaMessage.tenant_id == tenant.id).order_by(MemoryQaMessage.id).all()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Does this tenant have pets?"
    assert messages[1].role == "assistant"


def test_ask_endpoint_requires_nonblank_question(user_client, db_session):
    tenant = _create_tenant(db_session)
    response = user_client.post(f"/api/tenants/{tenant.id}/memory-qa", json={"question": "   "})
    assert response.status_code == 400


def test_profile_context_toggles_control_which_tenant_sections_are_sent(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(
        memory_qa_service.AiAgentProfile(
            name="QA",
            role=memory_qa_service.MEMORY_QA_ROLE,
            is_default=True,
            include_beds24=False,
            include_payments=False,
            include_notes=False,
            include_availability=False,
            include_brain_index=False,
            history_limit=0,
        )
    )
    db_session.commit()

    captured_prompt = {}

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        captured_prompt["prompt"] = prompt
        return gemini_client.GenerationResult(text="Answer.", parsed=None, model="fake", prompt_tokens=1, output_tokens=1, latency_ms=1)

    monkeypatch.setattr(memory_qa_service.gemini_client, "generate", fake_generate)

    memory_qa_service.answer_question(db_session, tenant, "What do we know?")

    prompt = captured_prompt["prompt"]
    assert "Structured Fields" in prompt
    assert "Tenant Conversation History" not in prompt
    assert "Booking Information (Beds24)" not in prompt
    assert "Payments & Charges" not in prompt
    assert "Internal Notes" not in prompt
    assert "Room Availability (Beds24)" not in prompt
    assert "Knowledge Base Index" not in prompt


def test_history_endpoint_returns_persisted_turns(user_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(text="Answer.", parsed=None, model="fake", prompt_tokens=1, output_tokens=1, latency_ms=1)

    monkeypatch.setattr(memory_qa_service.gemini_client, "generate", fake_generate)

    ask_response = user_client.post(f"/api/tenants/{tenant.id}/memory-qa", json={"question": "What's the check-in date?"})
    assert ask_response.status_code == 201

    history_response = user_client.get(f"/api/tenants/{tenant.id}/memory-qa")
    assert history_response.status_code == 200
    roles = [m["role"] for m in history_response.json()]
    assert roles == ["user", "assistant"]
