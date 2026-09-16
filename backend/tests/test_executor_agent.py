"""Regression tests for the executor agent.

The executor is the only role that ever writes to Beds24. It judges a Beds24 write the sales
manager prepared locally (an invoice-item update or a brand-new booking) against the operator's
own natural-language rules (its profile.instructions), then applies it if approved -
ai_agent_orchestrator.run_executor_validation resolves the profile and runs the judgement as its
own auditable AiAgentRun; ai_auto_draft_service._execute_pending performs the actual Beds24 write.
"""

import json

import pytest

from app.models.ai_agent_profile import AiAgentProfile
from app.models.ai_agent_run import AiAgentRun
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import ai_agent_orchestrator, gemini_client


def _tenant(db_session):
    tenant = Tenant(
        name="Executor Tenant", booking_id="B-exec-1", first_name="Sam", last_name="Jones",
        room_name="Studio A", check_in="2026-02-01", check_out="2026-02-05", num_adults=2, num_children=0,
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _profile(db_session, role, **overrides):
    defaults = dict(
        name=f"Default {role}", role=role, is_default=True, is_active=True,
        instructions=f"You are the {role}.", escalate_keywords=[],
    )
    defaults.update(overrides)
    profile = AiAgentProfile(**defaults)
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


class _FakeGemini:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None, file_parts=None):
        self.calls.append(prompt)
        payload = self.responses.pop(0)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return gemini_client.GenerationResult(
            text=text, parsed=payload if isinstance(payload, dict) else None,
            model=model or "fake-model", prompt_tokens=10, output_tokens=5, latency_ms=1,
        )


@pytest.fixture()
def fake_gemini(monkeypatch):
    def _install(responses):
        fake = _FakeGemini(responses)
        monkeypatch.setattr(ai_agent_orchestrator.gemini_client, "generate", fake)
        return fake

    return _install


def test_run_executor_validation_approves(db_session, fake_gemini):
    tenant = _tenant(db_session)
    _profile(db_session, "executor")
    fake_gemini([{"approved": True, "reason": "Guest confirmed the price in chat.", "blocking_issues": []}])

    pending = {
        "action": "update",
        "booking_id": tenant.booking_id,
        "invoice_items": [{"type": "charge", "description": "Studio A", "qty": 4, "amount": 100, "vat_rate": 9}],
    }

    result, run_id = ai_agent_orchestrator.run_executor_validation(
        db_session, tenant=tenant, pending_execution=pending, price_context="4 nights = EUR 400."
    )
    db_session.commit()

    assert result.approved is True
    assert "confirmed" in result.reason
    run = db_session.query(AiAgentRun).filter(AiAgentRun.id == run_id).one()
    assert run.status == ai_agent_orchestrator.STATUS_COMPLETED
    assert run.mode == "executor"
    assert [s.stage for s in run.steps] == ["executor"]


def test_run_executor_validation_blocks_with_reason(db_session, fake_gemini):
    tenant = _tenant(db_session)
    _profile(db_session, "executor")
    fake_gemini([
        {
            "approved": False,
            "reason": "The guest has not explicitly accepted this price yet.",
            "blocking_issues": ["No explicit acceptance in the conversation"],
        }
    ])

    pending = {
        "action": "update",
        "booking_id": tenant.booking_id,
        "invoice_items": [{"type": "charge", "description": "Studio A", "qty": 4, "amount": 100, "vat_rate": 9}],
    }

    result, run_id = ai_agent_orchestrator.run_executor_validation(
        db_session, tenant=tenant, pending_execution=pending, price_context="4 nights = EUR 400."
    )
    db_session.commit()

    assert result.approved is False
    assert "not explicitly accepted" in result.reason
    assert "No explicit acceptance" in result.reason
    run = db_session.query(AiAgentRun).filter(AiAgentRun.id == run_id).one()
    assert run.status == ai_agent_orchestrator.STATUS_ESCALATED
    assert run.escalation_reason == "executor_blocked"


def test_run_executor_validation_renders_create_payload(db_session, fake_gemini):
    tenant = _tenant(db_session)
    _profile(db_session, "executor")
    fake = fake_gemini([{"approved": True, "reason": "New booking looks consistent.", "blocking_issues": []}])

    pending = {
        "action": "create",
        "create_payload": {
            "room_id": 42,
            "arrival": "2026-03-01",
            "departure": "2026-03-05",
            "status": "inquiry",
            "first_name": "Alex",
            "last_name": "Doe",
            "email": "alex@example.com",
            "phone": "",
            "num_adults": 2,
            "num_children": 0,
            "invoice_items": [{"type": "charge", "description": "Studio B", "qty": 4, "amount": 90, "vat_rate": 9}],
        },
    }

    result, _run_id = ai_agent_orchestrator.run_executor_validation(
        db_session, tenant=tenant, pending_execution=pending
    )
    db_session.commit()

    assert result.approved is True
    prompt = fake.calls[0]
    assert "create a brand-new Beds24 booking" in prompt
    assert "room_id: 42" in prompt
    assert "Studio B" in prompt


def test_run_executor_validation_missing_profile_blocks(db_session):
    tenant = _tenant(db_session)
    # No executor profile configured.
    pending = {"action": "update", "booking_id": tenant.booking_id, "invoice_items": []}

    result, run_id = ai_agent_orchestrator.run_executor_validation(
        db_session, tenant=tenant, pending_execution=pending
    )

    assert result.approved is False
    assert "No executor profile" in result.reason
    assert run_id is None


def test_run_executor_validation_uses_tenant_pinned_profile(db_session, fake_gemini):
    tenant = _tenant(db_session)
    _profile(db_session, "executor", name="Global default executor")
    pinned = _profile(db_session, "executor", name="Strict executor", is_default=False, instructions="Never approve anything.")
    db_session.add(TenantAiSettings(tenant_id=tenant.id, executor_profile_id=pinned.id))
    db_session.commit()

    fake = fake_gemini([{"approved": False, "reason": "Blocked by strict policy.", "blocking_issues": []}])
    pending = {"action": "update", "booking_id": tenant.booking_id, "invoice_items": []}

    result, _run_id = ai_agent_orchestrator.run_executor_validation(
        db_session, tenant=tenant, pending_execution=pending
    )
    db_session.commit()

    assert result.approved is False
    assert "Never approve anything." in fake.calls[0]
