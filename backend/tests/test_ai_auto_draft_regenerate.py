from app.models.ai_auto_draft import AiAutoDraft
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import ai_agent_orchestrator, ai_auto_draft_service
from app.services.ai_agent_orchestrator import PlannerRunResult
from app.services.ai_auto_draft_service import regenerate_draft_via_planner


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

    result = regenerate_draft_via_planner(db_session, draft, "make it shorter and mention the deposit")

    assert result is draft
    assert draft.id == original_id
    assert captured_kwargs["operator_note"] == "make it shorter and mention the deposit"
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

    regenerate_draft_via_planner(db_session, draft, "tighten this up")

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

    regenerate_draft_via_planner(db_session, draft, "try again")

    assert draft.status == "needs_review"


def test_regenerate_returns_none_and_leaves_draft_untouched_when_planner_produces_nothing(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    draft = _create_draft(db_session, tenant, generated_text="Untouched original.")

    def fake_run_planner_loop(db, **kwargs):
        return PlannerRunResult(status="skipped", run_id=1002, generated_text=None)

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", fake_run_planner_loop)

    result = regenerate_draft_via_planner(db_session, draft, "try again")

    assert result is None
    assert draft.generated_text == "Untouched original."
    assert draft.status == "pending"


def test_regenerate_returns_none_when_ai_settings_missing(db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-regen-draft-no-settings")
    draft = _create_draft(db_session, tenant)

    def fake_run_planner_loop(db, **kwargs):
        raise AssertionError("planner must not be invoked without ai_settings")

    monkeypatch.setattr(ai_agent_orchestrator, "run_planner_loop", fake_run_planner_loop)

    result = regenerate_draft_via_planner(db_session, draft, "try again")

    assert result is None
