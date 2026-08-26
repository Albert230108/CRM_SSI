from app.models.ai_auto_draft import AiAutoDraft
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services import ai_agent_orchestrator, ai_auto_draft_service
from app.services.ai_agent_orchestrator import PlannerRunResult
from app.services.ai_auto_draft_service import regenerate_draft_via_planner, send_scheduled_draft


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Regenerate Draft Tenant", booking_id="B-regen-draft-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_ai_settings(db_session, tenant, planner_mode="auto-draft"):
    settings = TenantAiSettings(tenant_id=tenant.id, planner_mode=planner_mode)
    db_session.add(settings)
    db_session.commit()
    return settings


def _create_draft(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        channel="whatsapp",
        generated_text="Original draft text.",
        status="pending",
        checker_feedback="looked fine",
    )
    defaults.update(overrides)
    draft = AiAutoDraft(**defaults)
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)
    return draft


def test_regenerate_updates_draft_in_place_with_operator_note(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    draft = _create_draft(db_session, tenant)
    original_id = draft.id

    captured_kwargs = {}

    def fake_run_planner_loop(db, **kwargs):
        captured_kwargs.update(kwargs)
        return PlannerRunResult(
            status="completed",
            run_id=999,
            generated_text="Shorter reply, deposit mentioned.",
            template_id=42,
            checker_passed=True,
            checker_feedback="tightened per admin note",
            auto_send_allowed=True,
        )

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", fake_run_planner_loop)

    result = regenerate_draft_via_planner(db_session, draft, "make it shorter and mention the deposit", None)

    assert result is draft
    assert draft.id == original_id
    assert captured_kwargs["operator_note"] == "Redo #1\nWhat: make it shorter and mention the deposit"
    assert captured_kwargs["channel"] == "whatsapp"
    assert "Shorter reply, deposit mentioned." in draft.generated_text
    assert draft.template_id == 42
    assert draft.agent_run_id == 999
    assert draft.checker_feedback == "tightened per admin note"
    # Never lands in pending_auto_send even though the checker approved it and the tenant's
    # planner_mode would otherwise allow it - a redo always needs a fresh human look.
    assert draft.status == "pending"
    assert draft.scheduled_send_at is None


def test_regenerate_never_auto_sends_even_in_auto_send_mode(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant, planner_mode="auto-send")
    tenant_ai_settings = db_session.query(TenantAiSettings).filter_by(tenant_id=tenant.id).one()
    tenant_ai_settings.auto_send_whatsapp = True
    db_session.commit()
    draft = _create_draft(db_session, tenant)

    def fake_run_planner_loop(db, **kwargs):
        return PlannerRunResult(
            status="completed",
            run_id=1000,
            generated_text="Auto-sendable text.",
            template_id=1,
            checker_passed=True,
            auto_send_allowed=True,
        )

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", fake_run_planner_loop)

    regenerate_draft_via_planner(db_session, draft, "tighten this up", None)

    assert draft.status == "pending"
    assert draft.scheduled_send_at is None


def test_regenerate_keeps_needs_review_status(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    draft = _create_draft(db_session, tenant)

    def fake_run_planner_loop(db, **kwargs):
        return PlannerRunResult(
            status="needs_review",
            run_id=1001,
            generated_text="Draft the checker didn't approve.",
            template_id=1,
            checker_passed=False,
            auto_send_allowed=False,
        )

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", fake_run_planner_loop)

    regenerate_draft_via_planner(db_session, draft, "try again", None)

    assert draft.status == "needs_review"


def test_regenerate_returns_none_and_leaves_draft_untouched_when_planner_produces_nothing(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    draft = _create_draft(db_session, tenant, generated_text="Untouched original.")

    def fake_run_planner_loop(db, **kwargs):
        return PlannerRunResult(status="skipped", run_id=1002, generated_text=None)

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", fake_run_planner_loop)

    result = regenerate_draft_via_planner(db_session, draft, "try again", None)

    assert result is None
    assert draft.generated_text == "Untouched original."
    assert draft.status == "pending"


def test_regenerate_returns_none_when_ai_settings_missing(db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-regen-draft-no-settings")
    draft = _create_draft(db_session, tenant)

    def fake_run_planner_loop(db, **kwargs):
        raise AssertionError("planner must not be invoked without ai_settings")

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", fake_run_planner_loop)

    result = regenerate_draft_via_planner(db_session, draft, "try again", None)

    assert result is None


def test_sending_a_whatsapp_draft_never_includes_the_quoted_context(db_session, monkeypatch):
    # Regression: "Replying to: ..." must stay admin-facing only (quoted_context) - it must
    # never appear in what's actually sent to the guest via generated_text.
    tenant = _create_tenant(db_session, booking_id="B-regen-draft-send")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="31612345678@c.us",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    draft = _create_draft(
        db_session,
        tenant,
        whatsapp_endpoint_id=endpoint.id,
        generated_text="Yes, still available!",
        quoted_context='Replying to: "Is the room still available?"',
    )

    sent_messages = []

    async def fake_send_whatsapp_message(payload):
        sent_messages.append(payload["message"])
        return {}

    def fake_persist(db, **kwargs):
        class _Result:
            communication = type("_Communication", (), {"id": 1})()

        return _Result()

    monkeypatch.setattr(ai_auto_draft_service, "send_whatsapp_message", fake_send_whatsapp_message)
    monkeypatch.setattr(ai_auto_draft_service, "persist_whatsapp_outbound_communication", fake_persist)

    sent = send_scheduled_draft(db_session, draft)

    assert sent is True
    assert sent_messages == ["Yes, still available!"]
    assert "Replying to" not in sent_messages[0]


def test_regenerate_accumulates_prior_redo_history(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    draft = _create_draft(db_session, tenant)
    db_session.add(RedoRequestLog(ai_auto_draft_id=draft.id, tenant_id=tenant.id, channel="crm", what="make it friendlier", why="guest is sensitive", requested_by_user_id=1))
    db_session.commit()

    captured_kwargs = {}

    def fake_run_planner_loop(db, **kwargs):
        captured_kwargs.update(kwargs)
        return PlannerRunResult(
            status="completed",
            run_id=1003,
            generated_text="Reworked reply.",
            template_id=42,
            checker_passed=True,
            checker_feedback="tightened per admin note",
            auto_send_allowed=True,
        )

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", fake_run_planner_loop)

    regenerate_draft_via_planner(db_session, draft, "mention the parking code", "the guest asked twice")

    assert captured_kwargs["operator_note"] == (
        "Redo #1\nWhat: make it friendlier\nWhy: guest is sensitive\n\n"
        "Redo #2\nWhat: mention the parking code\nWhy: the guest asked twice"
    )
