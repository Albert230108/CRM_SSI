"""Regression tests for the planner choosing the outbound channel.

Before this change the planner was channel-agnostic: a reply always went out on whichever
channel the conversation last used, so an instruction like "reply on WhatsApp" was ignored.
The planner now emits a `channel` field; automated paths honour it (re-targeting the send),
manual runs keep the operator's explicit pick, and an unreachable choice escalates.
"""

import json

import pytest

from app.models.ai_agent_profile import AiAgentProfile
from app.models.ai_reply_template import AiReplyTemplate
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services import ai_agent_orchestrator, gemini_client


def _tenant(db_session):
    tenant = Tenant(name="Channel Tenant", booking_id="B-chan-1", first_name="Sam")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _template(db_session):
    template = AiReplyTemplate(
        name="General reply",
        description="Use for general questions.",
        sections=[{"label": "Persona", "content": "You are a helpful host."}],
        created_by_user_id=1,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _profile(db_session, role):
    profile = AiAgentProfile(
        name=f"Default {role}",
        role=role,
        is_default=True,
        is_active=True,
        instructions=f"You are the {role}.",
        escalate_keywords=[],
        history_limit=10,
        min_confidence=0.5,
        max_redraft_attempts=2,
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


def _settings(db_session, tenant, **overrides):
    defaults = dict(tenant_id=tenant.id, planner_mode="manual")
    defaults.update(overrides)
    settings = TenantAiSettings(**defaults)
    db_session.add(settings)
    db_session.commit()
    return settings


def _whatsapp_endpoint(db_session, tenant):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-web",
        external_account_id="acct-1",
        external_phone_id="phone-1",
        external_chat_namespace="3161234567@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint


class _FakeGemini:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None, file_parts=None):
        payload = self.responses.pop(0)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return gemini_client.GenerationResult(
            text=text,
            parsed=payload if isinstance(payload, dict) else None,
            model=model or "fake-model",
            prompt_tokens=10,
            output_tokens=5,
            latency_ms=1,
        )


@pytest.fixture()
def fake_gemini(monkeypatch):
    def _install(responses):
        monkeypatch.setattr(ai_agent_orchestrator.gemini_client, "generate", _FakeGemini(responses))

    return _install


def _plan(template_id, **overrides):
    payload = {
        "should_reply": True,
        "template_id": template_id,
        "extra_brain_sections": [],
        "extra_instructions": "Answer the question.",
        "confidence": 0.9,
        "reasoning": "Straightforward question.",
    }
    payload.update(overrides)
    return payload


def test_planner_channel_flip_retargets_when_respected(db_session, fake_gemini):
    """An email-inbound run whose planner picks whatsapp re-targets to the linked chat."""
    tenant = _tenant(db_session)
    template = _template(db_session)
    endpoint = _whatsapp_endpoint(db_session, tenant)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake_gemini([_plan(template.id, channel="whatsapp"), "Reply body.", {"passed": True, "feedback": ""}])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session,
        tenant=tenant,
        channel="email",
        mode="manual",
        inbound_text="Please reply on WhatsApp.",
        respect_planner_channel=True,
    )
    db_session.commit()

    assert result.status == "completed"
    assert result.chosen_channel == "whatsapp"
    assert result.chosen_whatsapp_endpoint_id == endpoint.id
    assert result.chosen_email_thread_id is None


def test_planner_channel_unreachable_escalates(db_session, fake_gemini):
    """Picking whatsapp with no linked chat parks the reply for a human instead of sending."""
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    # No WhatsApp endpoint linked. Only the planner call should happen - no draft/checker.
    fake_gemini([_plan(template.id, channel="whatsapp")])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session,
        tenant=tenant,
        channel="email",
        mode="manual",
        inbound_text="Please reply on WhatsApp.",
        respect_planner_channel=True,
    )
    db_session.commit()

    assert result.status == ai_agent_orchestrator.STATUS_ESCALATED
    assert result.escalation_reason == "channel_unavailable"
    assert result.generated_text is None


def test_manual_run_ignores_planner_channel(db_session, fake_gemini):
    """With respect_planner_channel False (manual UI), the operator's channel is kept."""
    tenant = _tenant(db_session)
    template = _template(db_session)
    _whatsapp_endpoint(db_session, tenant)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake_gemini([_plan(template.id, channel="whatsapp"), "Reply body.", {"passed": True, "feedback": ""}])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session,
        tenant=tenant,
        channel="email",
        mode="manual",
        inbound_text="Please reply on WhatsApp.",
        respect_planner_channel=False,
    )
    db_session.commit()

    assert result.status == "completed"
    assert result.chosen_channel is None
