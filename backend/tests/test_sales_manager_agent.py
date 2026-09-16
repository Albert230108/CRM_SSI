"""Regression tests for the sales-manager agent.

The planner can now ask, via a `sales_request`, for a stay to be priced (and optionally quoted as
a PDF) before the reply is drafted. A new full LLM agent - the sales manager - runs between the
planner and the drafter, prices the stay through the quotation-manager service, hands the drafter
the exact figures, and (for pdf/both) produces a PDF that is attached to the outgoing message.
"""

import json

import pytest

from app.models.ai_agent_profile import AiAgentProfile
from app.models.ai_agent_run import AiAgentRun
from app.models.ai_reply_template import AiReplyTemplate
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import ai_agent_orchestrator, ai_auto_draft_service, gemini_client, sales_manager_service


def _tenant(db_session):
    tenant = Tenant(
        name="Quote Tenant", booking_id="B-quote-1", first_name="Sam", last_name="Jones",
        room_name="Studio A", check_in="2026-02-01", check_out="2026-02-05", num_adults=2, num_children=0,
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _template(db_session):
    template = AiReplyTemplate(
        name="Quote reply", description="Use for pricing/quote requests.",
        sections=[{"label": "Persona", "content": "You are a helpful host."}], created_by_user_id=1,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _profile(db_session, role):
    profile = AiAgentProfile(
        name=f"Default {role}", role=role, is_default=True, is_active=True,
        instructions=f"You are the {role}.", escalate_keywords=[], history_limit=10,
        min_confidence=0.5, max_redraft_attempts=2,
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


def _plan(template_id, sales_request=None):
    payload = {
        "should_reply": True,
        "template_id": template_id,
        "extra_brain_sections": [],
        "extra_instructions": "Quote the stay.",
        "confidence": 0.9,
        "reasoning": "Guest asked for a price.",
    }
    if sales_request is not None:
        payload["sales_request"] = sales_request
    return payload


def _stub_charges(monkeypatch):
    quote = sales_manager_service.SalesQuote(
        nights=4, total_guests=2,
        charges=[{"kind": "accommodation", "description": "Studio A x 4 nights", "qty": 4, "amount": 100, "vat_rate": 9}],
        notes=["City tax excluded"],
    )
    monkeypatch.setattr(sales_manager_service, "compute_charges", lambda *a, **k: quote)
    return quote


def test_sales_request_price_only_feeds_drafter_no_pdf(db_session, fake_gemini, monkeypatch):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _profile(db_session, "sales_manager")
    _settings(db_session, tenant)
    _stub_charges(monkeypatch)
    # If a PDF were requested this would be called; assert it is NOT for scope="price".
    monkeypatch.setattr(
        sales_manager_service, "generate_quotation_pdf",
        lambda *a, **k: pytest.fail("PDF must not be generated for scope=price"),
    )
    fake = fake_gemini([
        _plan(template.id, {"needed": True, "scope": "price"}),
        {"price_summary": "4 nights at EUR 100 = EUR 400.", "security_deposit": 200, "notes": ""},
        "Dear Sam, your stay is EUR 400.",
        {"passed": True, "feedback": ""},
    ])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="How much for my stay?"
    )
    db_session.commit()

    assert result.status == "completed"
    assert result.quotation_file_path is None
    stages = [s.stage for s in db_session.query(AiAgentRun).filter(AiAgentRun.id == result.run_id).one().steps]
    assert stages == ["planner", "sales_manager", "drafter", "checker"]
    # The drafter prompt (4th gemini call) carries the sales manager's exact figures.
    assert "EUR 400" in fake.calls[2]


def test_sales_request_both_generates_and_carries_pdf(db_session, fake_gemini, monkeypatch):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _profile(db_session, "sales_manager")
    _settings(db_session, tenant)
    _stub_charges(monkeypatch)
    captured = {}

    def fake_pdf(tenant_arg, params, invoice_items, *, security_deposit, issued_by_user_id=None):
        captured["security_deposit"] = security_deposit
        captured["invoice_items"] = invoice_items
        return sales_manager_service.QuotationPdf(
            file_path="2026/B-quote-1_Sam_Jones/Quotation_B-quote-1_007.pdf",
            filename="Quotation_B-quote-1.pdf",
            web_url="https://onedrive/quote.pdf", quotation_number=7, location="local",
        )

    monkeypatch.setattr(sales_manager_service, "generate_quotation_pdf", fake_pdf)
    fake_gemini([
        _plan(template.id, {"needed": True, "scope": "both"}),
        {"price_summary": "4 nights = EUR 400.", "security_deposit": 250, "notes": "Deposit refundable."},
        "Dear Sam, quotation attached.",
        {"passed": True, "feedback": ""},
    ])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Send me a quote please."
    )
    db_session.commit()

    assert result.status == "completed"
    assert result.quotation_file_path == "2026/B-quote-1_Sam_Jones/Quotation_B-quote-1_007.pdf"
    assert result.quotation_pdf_filename == "Quotation_B-quote-1.pdf"
    assert result.quotation_web_url == "https://onedrive/quote.pdf"
    # The security deposit the model chose (250) flows into the PDF, and the priced lines become items.
    assert captured["security_deposit"] == 250
    assert captured["invoice_items"] and captured["invoice_items"][0]["type"] == "charge"


def test_no_sales_request_skips_sales_manager(db_session, fake_gemini, monkeypatch):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _profile(db_session, "sales_manager")
    _settings(db_session, tenant)
    monkeypatch.setattr(
        sales_manager_service, "compute_charges",
        lambda *a, **k: pytest.fail("Sales manager must not run without a sales_request"),
    )
    fake_gemini([_plan(template.id), "Dear Sam, thanks.", {"passed": True, "feedback": ""}])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="Just saying hi."
    )
    db_session.commit()

    assert result.status == "completed"
    stages = [s.stage for s in db_session.query(AiAgentRun).filter(AiAgentRun.id == result.run_id).one().steps]
    assert stages == ["planner", "drafter", "checker"]


def test_sales_request_update_quotation_execute_prepares_pending_execution_no_push(db_session, fake_gemini, monkeypatch):
    """action="update_quotation" with execute=true prepares a Beds24 invoice-item update on the
    result but never pushes it - the sales manager is strictly local. Only the executor agent,
    validated on a human-approved (or autonomous) draft send, ever pushes to Beds24 - see
    ai_auto_draft_service._execute_pending."""
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _profile(db_session, "sales_manager")
    _settings(db_session, tenant)
    _stub_charges(monkeypatch)
    monkeypatch.setattr(
        "app.services.beds24_service.update_booking_invoice_items",
        lambda *a, **k: pytest.fail("The sales manager must never push to Beds24 itself"),
    )
    fake_gemini([
        _plan(template.id, {"needed": True, "scope": "price", "action": "update_quotation", "execute": True}),
        {"price_summary": "Updated stay: EUR 400.", "security_deposit": 200, "notes": ""},
        "Dear Sam, here is your updated price.",
        {"passed": True, "feedback": ""},
    ])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual",
        inbound_text="Please update my booking to 4 nights.",
    )
    db_session.commit()

    assert result.status == "completed"
    assert result.pending_execution == {
        "action": "update",
        "booking_id": tenant.booking_id,
        "invoice_items": [
            {"type": "charge", "description": "Studio A x 4 nights", "qty": 4, "amount": 100, "vat_rate": 9},
        ],
    }


def test_sales_request_update_quotation_without_execute_prepares_nothing(db_session, fake_gemini, monkeypatch):
    """An ordinary update quote (execute not set) never prepares a Beds24 write at all."""
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    _profile(db_session, "sales_manager")
    _settings(db_session, tenant)
    _stub_charges(monkeypatch)
    fake_gemini([
        _plan(template.id, {"needed": True, "scope": "price", "action": "update_quotation"}),
        {"price_summary": "Updated stay: EUR 400.", "security_deposit": 200, "notes": ""},
        "Dear Sam, here is your updated price.",
        {"passed": True, "feedback": ""},
    ])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual",
        inbound_text="What would 4 nights cost?",
    )
    db_session.commit()

    assert result.status == "completed"
    assert result.pending_execution is None


def test_apply_result_with_pending_execution_never_auto_sends_in_manual_mode(db_session, monkeypatch):
    """Even with auto-send enabled and an approved draft, a prepared Beds24 action forces
    `pending`, never `pending_auto_send`, when the tenant's executor mode is manual (the default:
    no AdminSettings row means _resolve_executor_mode falls back to "manual") - the write only
    ever happens once a human approves it."""
    from app.models.ai_auto_draft import AiAutoDraft

    tenant = _tenant(db_session)
    template = _template(db_session)
    ai_settings = _settings(db_session, tenant, planner_mode="auto-send", auto_send_email=True)

    pending = {
        "action": "update",
        "booking_id": tenant.booking_id,
        "invoice_items": [{"type": "charge", "description": "Studio A", "qty": 1, "amount": 100, "vat_rate": 9}],
    }

    class _Result:
        status = "completed"
        auto_send_allowed = True
        generated_text = "Dear Sam, updated price attached."
        formatted_text = None
        template_id = template.id
        run_id = None
        checker_feedback = None
        chosen_channel = None
        chosen_email_thread_id = None
        chosen_whatsapp_endpoint_id = None
        quotation_file_path = None
        quotation_pdf_filename = None
        quotation_web_url = None
        pending_execution = pending

    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="", status="pending")
    db_session.add(draft)
    db_session.commit()

    ai_auto_draft_service.apply_planner_result_to_draft(
        db_session, draft, tenant=tenant, ai_settings=ai_settings, channel="email",
        result=_Result(), inbound_text="Please update my booking.",
    )
    db_session.commit()

    assert draft.status == "pending"
    assert draft.scheduled_send_at is None
    assert draft.pending_execution == pending


def test_apply_result_with_pending_execution_auto_sends_in_autonomous_mode(db_session, monkeypatch):
    """With the tenant's executor mode set to autonomous, an approved draft carrying a prepared
    Beds24 action is allowed into pending_auto_send like any other approved draft - the executor
    itself still validates (and can still block) the write when the timer actually sends it."""
    from app.models.ai_auto_draft import AiAutoDraft

    tenant = _tenant(db_session)
    template = _template(db_session)
    ai_settings = _settings(
        db_session, tenant, planner_mode="auto-send", auto_send_email=True, executor_mode="autonomous"
    )

    pending = {
        "action": "update",
        "booking_id": tenant.booking_id,
        "invoice_items": [{"type": "charge", "description": "Studio A", "qty": 1, "amount": 100, "vat_rate": 9}],
    }

    class _Result:
        status = "completed"
        auto_send_allowed = True
        generated_text = "Dear Sam, updated price attached."
        formatted_text = None
        template_id = template.id
        run_id = None
        checker_feedback = None
        chosen_channel = None
        chosen_email_thread_id = None
        chosen_whatsapp_endpoint_id = None
        quotation_file_path = None
        quotation_pdf_filename = None
        quotation_web_url = None
        pending_execution = pending

    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="", status="pending")
    db_session.add(draft)
    db_session.commit()

    ai_auto_draft_service.apply_planner_result_to_draft(
        db_session, draft, tenant=tenant, ai_settings=ai_settings, channel="email",
        result=_Result(), inbound_text="Please update my booking.",
    )
    db_session.commit()

    assert draft.status == "pending_auto_send"
    assert draft.scheduled_send_at is not None


def test_missing_sales_manager_profile_escalates(db_session, fake_gemini, monkeypatch):
    tenant = _tenant(db_session)
    template = _template(db_session)
    _profile(db_session, "planner")
    _profile(db_session, "checker")
    # No sales_manager profile exists.
    _settings(db_session, tenant)
    fake_gemini([_plan(template.id, {"needed": True, "scope": "price"})])

    result = ai_agent_orchestrator.run_planner_loop(
        db_session, tenant=tenant, channel="email", mode="manual", inbound_text="How much?"
    )
    db_session.commit()

    assert result.status == ai_agent_orchestrator.STATUS_ESCALATED
    assert result.escalation_reason == "sales_manager_unavailable"


def test_apply_result_persists_quotation_path(db_session, monkeypatch):
    """The shared apply step stores the PDF's path/filename (not its bytes) so the send path can
    read and attach it lazily - see ai_auto_draft_service._draft_quotation_attachments."""
    from app.models.ai_auto_draft import AiAutoDraft

    tenant = _tenant(db_session)
    template = _template(db_session)
    ai_settings = _settings(db_session, tenant)

    class _Result:
        status = "completed"
        auto_send_allowed = False
        generated_text = "Dear Sam, quotation attached."
        formatted_text = None
        template_id = template.id
        run_id = None
        checker_feedback = None
        chosen_channel = None
        chosen_email_thread_id = None
        chosen_whatsapp_endpoint_id = None
        quotation_file_path = "2026/B-quote-1_Sam_Jones/Quotation_B-quote-1_007.pdf"
        quotation_pdf_filename = "Quotation_B-quote-1.pdf"
        quotation_web_url = "https://onedrive/quote.pdf"
        pending_execution = None

    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="", status="pending")
    db_session.add(draft)
    db_session.commit()

    ai_auto_draft_service.apply_planner_result_to_draft(
        db_session, draft, tenant=tenant, ai_settings=ai_settings, channel="email",
        result=_Result(), inbound_text="How much?",
    )
    db_session.commit()

    assert draft.quotation_file_path == "2026/B-quote-1_Sam_Jones/Quotation_B-quote-1_007.pdf"
    assert draft.quotation_filename == "Quotation_B-quote-1.pdf"
