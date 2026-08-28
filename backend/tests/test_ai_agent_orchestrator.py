import json
from datetime import date, datetime, timezone

import pytest

from app.models.ai_agent_profile import AiAgentProfile
from app.models.action_tag_definition import ActionTagDefinition
from app.models.ai_agent_run import AiAgentRun, AiAgentRunStep
from app.models.ai_reply_template import AiReplyTemplate
from app.models.brain_field_definition import BrainFieldDefinition
from app.models.brain_section import BrainSection
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_ai_template_link import TenantAiTemplateLink
from app.models.tenant_brain_entry import TenantBrainEntry
from app.models.tenant_brain_field_value import TenantBrainFieldValue
from app.models.tenant_conversation_link import TenantConversationLink
from app.services import action_item_service, ai_agent_orchestrator, ai_auto_draft_service, attachment_service, gemini_client


def _tenant(db_session, **overrides):
    defaults = dict(name="Planner Tenant", booking_id="B-plan-1", first_name="Alex")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _template(db_session, name="Late check-in", description="Use for late arrival requests."):
    template = AiReplyTemplate(
        name=name,
        description=description,
        sections=[{"label": "Persona", "content": "You are a helpful host."}],
        created_by_user_id=1,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _profile(db_session, role, **overrides):
    defaults = dict(
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
    defaults.update(overrides)
    profile = AiAgentProfile(**defaults)
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


def _brain_section(db_session, path, title, content):
    section = BrainSection(path=path, slug=path.rsplit(".", 1)[-1], title=title, content=content)
    db_session.add(section)
    db_session.commit()
    db_session.refresh(section)
    return section


class _FakeGemini:
    """Serves canned responses in order, recording every prompt the loop sends."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(
        self, prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None, file_parts=None
    ):
        self.calls.append({
            "prompt": prompt,
            "model": model,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "schema": response_schema,
            "file_parts": file_parts,
        })
        if not self.responses:
            raise AssertionError("The loop made more model calls than the test provided responses for")
        payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
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
        fake = _FakeGemini(responses)
        monkeypatch.setattr(ai_agent_orchestrator.gemini_client, "generate", fake)
        return fake

    return _install


def _plan(template_id, **overrides):
    payload = {
        "should_reply": True,
        "template_id": template_id,
        "extra_brain_sections": [],
        "extra_instructions": "Confirm the 22:00 arrival.",
        "confidence": 0.9,
        "reasoning": "The guest asked about arriving late.",
        "alternatives": [{"template_id": 999, "why_not": "Not about cancellation."}],
    }
    payload.update(overrides)
    return payload


def test_happy_path_completes_on_first_check(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini([_plan(template.id), "Dear Alex, 22:00 is fine.", {"passed": True, "feedback": ""}])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Can I arrive at 22:00?"
    )
    db_session.commit()

    assert result.status == "completed"
    assert result.generated_text == "Dear Alex, 22:00 is fine."
    assert result.template_id == template.id
    assert result.checker_passed is True
    assert result.auto_send_allowed is True
    assert result.attempts == 1
    assert len(fake.calls) == 3

    run = db_session.query(AiAgentRun).filter(AiAgentRun.id == result.run_id).one()
    assert run.status == "completed"
    assert run.total_prompt_tokens == 30 and run.total_output_tokens == 15
    stages = [step.stage for step in run.steps]
    assert stages == ["planner", "drafter", "checker"]


def test_formatter_disabled_leaves_formatted_text_none(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _profile(db_session, "formatter")
    _settings(db_session, tenant)
    fake = fake_gemini([_plan(template.id), "Raw draft text.", {"passed": True, "feedback": ""}])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Can I arrive at 22:00?"
    )
    db_session.commit()

    assert result.generated_text == "Raw draft text."
    assert result.formatted_text is None
    assert len(fake.calls) == 3


@pytest.mark.parametrize(
    ("channel", "formatted_text"),
    [("email", "<p><strong>Hello</strong></p>"), ("whatsapp", "*Hello*")],
)
def test_formatter_enabled_populates_formatted_text_per_channel(db_session, fake_gemini, channel, formatted_text):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _profile(db_session, "formatter")
    _settings(db_session, tenant, formatter_enabled=True)
    fake = fake_gemini([
        _plan(template.id),
        "Raw draft text.",
        {"passed": True, "feedback": ""},
        {"formatted_text": formatted_text},
    ])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel=channel, mode="manual", inbound_text="Can I arrive at 22:00?"
    )
    db_session.commit()

    assert result.generated_text == "Raw draft text."
    assert result.formatted_text == formatted_text
    assert len(fake.calls) == 4
    assert ("## Email Formatting" if channel == "email" else "## WhatsApp Formatting") in fake.calls[-1]["prompt"]
    assert "Raw draft text." in fake.calls[-1]["prompt"]
    assert [step.stage for step in db_session.query(AiAgentRun).filter(AiAgentRun.id == result.run_id).one().steps] == [
        "planner",
        "drafter",
        "checker",
        "formatter",
    ]


def test_whatsapp_formatter_html_falls_back_before_persisting(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _profile(db_session, "formatter")
    _settings(db_session, tenant, planner_mode="auto-draft", formatter_enabled=True)
    fake = fake_gemini([
        _plan(template.id),
        "Raw draft text.",
        {"passed": True, "feedback": ""},
        {"formatted_text": "<p>Raw draft text.</p>"},
    ])

    trigger = AiAutoDraftTrigger(tenant_id=tenant.id, channel="whatsapp", trigger_at=datetime.now(timezone.utc))
    draft = ai_auto_draft_service.generate_draft_for_trigger(db_session, trigger)
    assert draft is not None

    db_session.commit()
    stored_draft = db_session.query(AiAutoDraft).filter(AiAutoDraft.id == draft.id).one()

    assert stored_draft.generated_text == "Raw draft text."
    assert stored_draft.formatted_text == "Raw draft text."
    assert "<" not in stored_draft.formatted_text
    assert len(fake.calls) == 4
    assert [step.stage for step in db_session.query(AiAgentRun).filter(AiAgentRun.id == stored_draft.agent_run_id).one().steps] == [
        "planner",
        "drafter",
        "checker",
        "formatter",
    ]


def test_formatter_failure_soft_fails_without_blocking_draft(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _profile(db_session, "formatter")
    _settings(db_session, tenant, formatter_enabled=True)
    fake = fake_gemini([
        _plan(template.id),
        "Raw draft text.",
        {"passed": True, "feedback": ""},
        gemini_client.GeminiClientError("formatter boom"),
    ])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Can I arrive at 22:00?"
    )
    db_session.commit()

    assert result.status == "completed"
    assert result.generated_text == "Raw draft text."
    assert result.formatted_text is None
    assert len(fake.calls) == 4
    run = db_session.query(AiAgentRun).filter(AiAgentRun.id == result.run_id).one()
    assert [step.stage for step in run.steps] == ["planner", "drafter", "checker", "formatter"]


def test_attachments_reach_every_stage_as_file_parts_and_an_explicit_instruction(db_session, fake_gemini):
    """Regression test: an eligible attachment must not just ride along as an inline file part -
    every stage's prompt needs an explicit instruction telling the model it's there and that it
    should actually be used, and since the run's audit trail (AiAgentRunStep.prompt) stores
    exactly the prompt string that was sent, that instruction must show up there too - an
    operator auditing the run afterward should be able to see that an attachment was involved
    without digging through server logs.
    """
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini([_plan(template.id), "Here's the reply.", {"passed": True, "feedback": ""}])

    attachment = attachment_service.OutboundAttachment(
        attachment_id=1, filename="damage-photo.png", mime_type="image/png", content=b"fake-png-bytes"
    )

    result = ai_agent_orchestrator.run_planner_loop(
        db_session,
        tenant=tenant,
        channel="email",
        mode="manual",
        inbound_text="See attached.",
        attachments=[attachment],
    )
    db_session.commit()

    assert len(fake.calls) == 3
    for call in fake.calls:
        assert call["file_parts"] == [gemini_client.FilePart(data=b"fake-png-bytes", mime_type="image/png")]
        assert "damage-photo.png (image/png)" in call["prompt"]

    run = db_session.query(AiAgentRun).filter(AiAgentRun.id == result.run_id).one()
    for step in run.steps:
        assert "damage-photo.png (image/png)" in step.prompt


def test_tenant_brain_blocks_reach_planner_and_checker_when_enabled(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner", include_tenant_brain=True)
    _profile(db_session, "checker", include_tenant_brain=True)
    _settings(db_session, tenant)
    field = BrainFieldDefinition(
        key="pets",
        label="Pets",
        ai_instruction="Track whether the tenant has pets.",
        is_active=True,
    )
    db_session.add(field)
    db_session.commit()
    db_session.add(TenantBrainFieldValue(tenant_id=tenant.id, field_definition_id=field.id, value="Has a dog", source="manual"))
    db_session.add(TenantBrainEntry(tenant_id=tenant.id, content="Prefers ground floor", source="manual"))
    db_session.commit()

    fake = fake_gemini([_plan(template.id), "Here's the reply.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Late arrival?"
    )
    db_session.commit()

    assert "## Structured Fields" in fake.calls[0]["prompt"]
    assert "- Pets: Has a dog" in fake.calls[0]["prompt"]
    assert "## Free-Text Brain Entries" in fake.calls[0]["prompt"]
    assert "- Prefers ground floor" in fake.calls[0]["prompt"]
    assert "## Structured Fields" in fake.calls[2]["prompt"]
    assert "- Pets: Has a dog" in fake.calls[2]["prompt"]
    assert "## Free-Text Brain Entries" in fake.calls[2]["prompt"]
    assert "- Prefers ground floor" in fake.calls[2]["prompt"]


def test_action_items_reach_planner_and_checker_regardless_of_status(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)

    tag = ActionTagDefinition(name="Plumbing", color="#0ea5e9")
    db_session.add(tag)
    db_session.commit()

    _open_item = action_item_service.create(
        db_session,
        tenant.id,
        "Fix leak in apartment 3",
        due_date=date(2026, 8, 27),
        tag_ids=[tag.id],
        priority="p1",
    )
    dismissed_item = action_item_service.create(
        db_session,
        tenant.id,
        "Double-check Wi-Fi extender",
        due_date=date(2026, 8, 28),
        priority="p2",
    )
    done_item = action_item_service.create(
        db_session,
        tenant.id,
        "Send welcome message",
        due_date=date(2026, 8, 26),
        priority="p3",
    )
    action_item_service.dismiss(db_session, dismissed_item)
    action_item_service.complete(db_session, done_item)

    fake = fake_gemini([_plan(template.id), "Here's the reply.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Late arrival?"
    )
    db_session.commit()

    expected_open = "- [open] (p1) Fix leak in apartment 3 - due 2026-08-27 [tags: Plumbing]"
    expected_dismissed = "- [dismissed] (p2) Double-check Wi-Fi extender - due 2026-08-28"
    expected_done = "- [done] (p3) Send welcome message - due 2026-08-26"
    planner_prompt = fake.calls[0]["prompt"]
    checker_prompt = fake.calls[2]["prompt"]
    for prompt in (planner_prompt, checker_prompt):
        assert "## Action Items" in prompt
        assert expected_open in prompt
        assert expected_dismissed in prompt
        assert expected_done in prompt


def test_tenant_with_no_action_items_gets_a_placeholder_line(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini([_plan(template.id), "Here's the reply.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Late arrival?"
    )
    db_session.commit()

    assert "No action items on file." in fake.calls[0]["prompt"]
    assert "No action items on file." in fake.calls[2]["prompt"]


def test_action_items_block_defaults_match_planner_and_checker_registry():
    assert ai_agent_orchestrator.ai_prompt_blocks.DEFAULTS_BY_ROLE[ai_agent_orchestrator.PLANNER_ROLE]["ctx_actions"] == "## Action Items"
    assert ai_agent_orchestrator.ai_prompt_blocks.DEFAULTS_BY_ROLE[ai_agent_orchestrator.CHECKER_ROLE]["ctx_actions"] == "## Action Items"


def test_unsupported_attachment_is_skipped_and_not_sent_to_the_model(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini([_plan(template.id), "Here's the reply.", {"passed": True, "feedback": ""}])

    attachment = attachment_service.OutboundAttachment(
        attachment_id=2, filename="notes.txt", mime_type="text/plain", content=b"hello"
    )

    ai_agent_orchestrator.run_planner_loop(
        db_session,
        tenant=tenant,
        channel="email",
        mode="manual",
        inbound_text="See attached.",
        attachments=[attachment],
    )
    db_session.commit()

    for call in fake.calls:
        assert call["file_parts"] is None
        assert "notes.txt" not in call["prompt"]


def test_planner_reasoning_and_alternatives_are_persisted(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Late arrival?"
    )
    db_session.commit()

    planner_step = (
        db_session.query(AiAgentRunStep)
        .filter(AiAgentRunStep.run_id == result.run_id, AiAgentRunStep.stage == "planner")
        .one()
    )
    assert planner_step.parsed["reasoning"] == "The guest asked about arriving late."
    assert planner_step.parsed["alternatives"][0]["why_not"] == "Not about cancellation."


def test_checker_rejection_triggers_a_redraft_with_feedback(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker", max_redraft_attempts=2)
    _settings(db_session, tenant)
    fake = fake_gemini(
        [
            _plan(template.id),
            "First draft in English.",
            {
                "passed": False,
                "feedback": "The guest wrote in Portuguese.",
                "issues": ["Wrong language", "Missing check-in time"],
            },
            "Segundo rascunho.",
            {"passed": True, "feedback": ""},
        ]
    )

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Posso chegar tarde?"
    )
    db_session.commit()

    assert result.status == "completed"
    assert result.generated_text == "Segundo rascunho."
    assert result.attempts == 2
    # The rejected draft's text, feedback and structured issues must all reach the second
    # drafting prompt, or the rewrite is blind to what it actually got wrong.
    second_draft_prompt = fake.calls[3]["prompt"]
    assert "5. Your Previous Draft (Rejected)" in second_draft_prompt
    assert "First draft in English." in second_draft_prompt
    assert "6. Reviewer Feedback" in second_draft_prompt
    assert "The guest wrote in Portuguese." in second_draft_prompt
    assert "Wrong language" in second_draft_prompt
    assert "Missing check-in time" in second_draft_prompt


def test_exhausted_attempts_park_the_draft_for_a_human(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker", max_redraft_attempts=1)
    _settings(db_session, tenant)
    fake_gemini(
        [
            _plan(template.id),
            "Draft one.",
            {"passed": False, "feedback": "Too formal."},
            "Draft two.",
            {"passed": False, "feedback": "Still too formal."},
        ]
    )

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="Hello"
    )
    db_session.commit()

    assert result.status == "needs_review"
    # The last draft is kept rather than discarded, so a human has something to work from.
    assert result.generated_text == "Draft two."
    assert result.checker_feedback == "Still too formal."
    assert result.checker_passed is False
    assert result.auto_send_allowed is False
    assert result.attempts == 2


def test_block_auto_send_on_fail_can_be_turned_off(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker", max_redraft_attempts=0, block_auto_send_on_fail=False)
    _settings(db_session, tenant)
    fake_gemini([_plan(template.id), "Draft.", {"passed": False, "feedback": "Meh."}])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="Hi"
    )

    assert result.status == "needs_review"
    assert result.auto_send_allowed is True


def test_escalate_keyword_short_circuits_before_any_model_call(db_session, fake_gemini):
    tenant = _tenant(db_session)
    _template(db_session)
    _profile(db_session, "planner", escalate_keywords=["refund", "lawyer"])
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini([])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="I want a REFUND immediately."
    )
    db_session.commit()

    assert result.status == "escalated"
    assert result.escalation_reason == "keyword:refund"
    assert result.generated_text is None
    assert fake.calls == []


def test_low_confidence_escalates(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner", min_confidence=0.8)
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake_gemini([_plan(template.id, confidence=0.3)])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="Hi"
    )

    assert result.status == "escalated"
    assert result.escalation_reason == "low_confidence"


def test_on_no_template_match_skip_produces_nothing(db_session, fake_gemini):
    tenant = _tenant(db_session)
    _template(db_session)
    _profile(db_session, "planner", on_no_template_match="skip")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake_gemini([_plan(None)])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="Hi"
    )

    assert result.status == "skipped"
    assert result.escalation_reason == "no_template_match"


def test_template_outside_the_tenants_available_set_is_rejected(db_session, fake_gemini):
    """A hallucinated or unlinked id must not draft from a template the operator never enabled."""
    tenant = _tenant(db_session)
    allowed = _template(db_session, name="Allowed")
    forbidden = _template(db_session, name="Forbidden")
    db_session.add(TenantAiTemplateLink(tenant_id=tenant.id, template_id=allowed.id))
    db_session.commit()
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini([_plan(forbidden.id)])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="Hi"
    )

    assert result.status == "escalated"
    assert result.escalation_reason == "no_template_match"
    assert "Forbidden" not in fake.calls[0]["prompt"]
    assert "Allowed" in fake.calls[0]["prompt"]


def test_should_reply_false_skips(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake_gemini([_plan(template.id, should_reply=False)])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="Thanks, bye!"
    )

    assert result.status == "skipped"
    assert result.escalation_reason == "planner_declined"


def test_daily_token_cap_escalates_without_calling_the_model(db_session, fake_gemini):
    tenant = _tenant(db_session)
    _template(db_session)
    _profile(db_session, "planner", daily_token_cap=100)
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    db_session.add(
        AiAgentRun(
            tenant_id=tenant.id,
            channel="email",
            mode="auto",
            status="completed",
            total_prompt_tokens=80,
            total_output_tokens=40,
        )
    )
    db_session.commit()
    fake = fake_gemini([])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="Hi"
    )

    assert result.status == "escalated"
    assert result.escalation_reason == "token_cap"
    assert fake.calls == []


def test_planner_extra_brain_sections_reach_the_draft_prompt(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    db_session.add(
        BrainSection(path="parking", slug="parking", title="Parking", content="Garage on level -1.")
    )
    db_session.commit()
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini(
        [
            _plan(template.id, extra_brain_sections=["parking"]),
            "Draft.",
            {"passed": True, "feedback": ""},
        ]
    )

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Where do I park?"
    )

    draft_prompt = fake.calls[1]["prompt"]
    assert "1b. Knowledge Base" in draft_prompt
    assert "Garage on level -1." in draft_prompt


def test_planner_always_include_brain_sections_are_rendered_in_full(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _brain_section(db_session, "policies.checkin", "Check-in", "Check-in is at 3pm.")
    _profile(db_session, "planner", always_include_brain_sections=["policies.checkin"])
    _profile(db_session, "checker")
    _settings(db_session, tenant)

    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Where do I park?"
    )

    planner_prompt = fake.calls[0]["prompt"]
    assert "## Always Included Brain Sections" in planner_prompt
    assert "Check-in is at 3pm." in planner_prompt
    assert "policies.checkin" in planner_prompt


def test_redo_uses_redo_temperature_override_and_leaves_unset_values_alone(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(
        db_session,
        "planner",
        temperature=0.2,
        redo_model="planner-redo",
        redo_temperature=0.8,
        redo_max_output_tokens=1111,
    )
    _profile(db_session, "checker", temperature=0.4)
    _profile(db_session, "drafter", temperature=0.6)
    _settings(db_session, tenant)

    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session,
        tenant=tenant,
        channel="email",
        mode="manual",
        inbound_text="Where do I park?",
        is_redo=True,
    )

    assert fake.calls[0]["model"] == "planner-redo"
    assert fake.calls[0]["temperature"] == 0.8
    assert fake.calls[0]["max_output_tokens"] == 1111
    assert fake.calls[1]["temperature"] == 0.6
    assert fake.calls[2]["temperature"] == 0.4


def test_redo_without_overrides_uses_the_normal_values(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner", temperature=0.25, max_output_tokens=1500)
    _profile(db_session, "checker", temperature=0.35)
    _profile(db_session, "drafter", temperature=0.45)
    _settings(db_session, tenant)

    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session,
        tenant=tenant,
        channel="email",
        mode="manual",
        inbound_text="Where do I park?",
        is_redo=True,
    )

    assert fake.calls[0]["temperature"] == 0.25
    assert fake.calls[0]["max_output_tokens"] == 1500
    assert fake.calls[1]["temperature"] == 0.45
    assert fake.calls[2]["temperature"] == 0.35


def test_operator_note_leads_the_drafter_instruction(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session,
        tenant=tenant,
        channel="email",
        mode="manual",
        inbound_text="Late arrival?",
        operator_note="Mention the lockbox code.",
    )

    planner_prompt = fake.calls[0]["prompt"]
    assert "Mention the lockbox code." in planner_prompt
    draft_prompt = fake.calls[1]["prompt"]
    assert draft_prompt.index("Mention the lockbox code.") < draft_prompt.index("Confirm the 22:00 arrival.")


def test_missing_planner_profile_fails_cleanly(db_session, fake_gemini):
    tenant = _tenant(db_session)
    _template(db_session)
    _settings(db_session, tenant)
    fake = fake_gemini([])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="Hi"
    )

    assert result.status == "failed"
    assert result.escalation_reason == "no_planner_profile"
    assert fake.calls == []


def test_checker_error_parks_the_draft_rather_than_losing_it(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake_gemini(
        [_plan(template.id), "Draft text.", gemini_client.GeminiClientError("checker exploded")]
    )

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="auto", inbound_text="Hi"
    )
    db_session.commit()

    assert result.status == "needs_review"
    assert result.generated_text == "Draft text."
    assert result.escalation_reason == "checker_error"
    assert result.auto_send_allowed is False


def test_tenant_pinned_profile_wins_over_the_default(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    default_planner = _profile(db_session, "planner", name="Standard")
    pinned = _profile(db_session, "planner", name="VIP", is_default=False, instructions="Be extra warm.")
    _profile(db_session, "checker")
    _settings(db_session, tenant, planner_profile_id=pinned.id)
    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Hi"
    )

    assert "Be extra warm." in fake.calls[0]["prompt"]
    run = db_session.query(AiAgentRun).filter(AiAgentRun.id == result.run_id).one()
    assert run.planner_profile_id == pinned.id
    assert run.planner_profile_id != default_planner.id


def test_profile_history_channel_filter_is_applied(db_session, fake_gemini):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner", history_channels="inbound")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="whatsapp", mode="manual", inbound_text="Hi"
    )

    assert "across WhatsApp" in fake.calls[0]["prompt"]


def test_planner_receives_inbound_email_body_in_prompt(db_session, fake_gemini):
    """Regression: the planner must see the latest inbound email in its ctx_inbound block."""
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    inbound_message = "Can I check in early at 2pm instead of 3pm?"
    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text=inbound_message
    )

    # The inbound message must appear in the planner prompt for decision-making context.
    planner_prompt = fake.calls[0]["prompt"]
    assert inbound_message in planner_prompt


def test_checker_receives_inbound_email_body_in_prompt(db_session, fake_gemini):
    """Regression: the checker must see the latest inbound email in its ctx_inbound block."""
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    inbound_message = "Can I check in early at 2pm instead of 3pm?"
    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text=inbound_message
    )

    # The inbound message must appear in the checker prompt to validate the draft against context.
    # fake.calls[2] is the checker call (0=planner, 1=drafter, 2=checker)
    checker_prompt = fake.calls[2]["prompt"]
    assert inbound_message in checker_prompt


def test_drafter_receives_inbound_email_body_in_prompt(db_session, fake_gemini):
    """Regression: the drafter used to get no ctx_inbound block at all.

    With a template that doesn't include history, the guest's message reached the drafter
    through no route whatsoever, so it wrote the reply having never read the question.
    """
    tenant = _tenant(db_session)
    template = _template(db_session)
    assert not template.include_history, "this test is only meaningful without history"
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    inbound_message = "Can I check in early at 2pm instead of 3pm?"
    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text=inbound_message
    )

    # fake.calls[1] is the drafter call (0=planner, 1=drafter, 2=checker).
    assert inbound_message in fake.calls[1]["prompt"]


def test_checker_receives_the_template_the_planner_chose(db_session, fake_gemini):
    """The checker must be able to tell whether the draft followed its template."""
    tenant = _tenant(db_session)
    template = _template(db_session, description="Planner-only: pick me for late arrivals.")
    template.guidelines = "Always confirm the exact arrival time back to the guest."
    db_session.commit()
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _settings(db_session, tenant)
    fake = fake_gemini([_plan(template.id), "Draft.", {"passed": True, "feedback": ""}])

    ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Arriving late"
    )

    checker_prompt = fake.calls[2]["prompt"]
    assert template.name in checker_prompt
    assert "Always confirm the exact arrival time back to the guest." in checker_prompt
    assert "You are a helpful host." in checker_prompt  # the template's sections
    # `description` tells the planner when to *pick* a template; it is not review criteria.
    assert "Planner-only: pick me for late arrivals." not in checker_prompt


def test_latest_inbound_text_ignores_hidden_threads(db_session):
    """A thread toggled hidden (is_visible=False) must never surface in AI prompts."""
    tenant = _tenant(db_session)
    thread = Conversation(provider="gmail", provider_thread_id="thread-hidden-inbound", subject="Hidden")
    db_session.add(thread)
    db_session.commit()
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=thread.id, is_visible=False))
    db_session.add(
        ConversationMessage(
            conversation_id=thread.id,
            provider="gmail",
            provider_message_id="msg-hidden-inbound",
            direction="inbound",
            body="Message from a hidden thread",
            sent_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    assert ai_agent_orchestrator.latest_inbound_text(db_session, tenant.id, "email") is None
