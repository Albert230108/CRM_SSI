from datetime import date, datetime, time, timezone

import pytest

from app.models.action_item import ActionItem
from app.models.action_tag_definition import ActionTagDefinition
from app.models.ai_auto_draft import AiAutoDraft
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import action_item_service, action_planner_trigger_service, gemini_client


def _tenant(db_session, **overrides):
    defaults = dict(name="Trigger Tenant", booking_id="B-trigger-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _enable_planner(db_session, tenant):
    db_session.add(TenantAiSettings(tenant_id=tenant.id, planner_mode="manual", auto_draft_email=True))
    db_session.commit()


def _trigger_tag(db_session, name="Planner"):
    tag = ActionTagDefinition(name=name, color="#123456", is_active=True, triggers_planner=True)
    db_session.add(tag)
    db_session.commit()
    db_session.refresh(tag)
    return tag


@pytest.fixture()
def capture_planner(monkeypatch):
    """Stub out the LLM planner run and the conversation-channel lookup so the sweep is deterministic."""
    calls = []

    def fake_run(db, *, draft_id, tenant_id, channel, operator_note, attachment_ids, user_id):
        calls.append({"draft_id": draft_id, "tenant_id": tenant_id, "channel": channel, "operator_note": operator_note})

    monkeypatch.setattr(action_planner_trigger_service, "run_ai_plan_for_draft", fake_run)
    monkeypatch.setattr(
        action_planner_trigger_service,
        "compute_last_message_by_tenant_id",
        lambda db, tenant_ids: {tid: (datetime.now(timezone.utc), "email", "inbound") for tid in tenant_ids},
    )
    # Default to "instruction names no channel" so the sweep falls back to the last-message channel
    # without a live Gemini call. Tests that exercise the override set this per-case.
    monkeypatch.setattr(action_planner_trigger_service, "extract_instructed_channel", lambda item: None)
    return calls


def test_due_tagged_tenant_action_fires_planner(db_session, capture_planner):
    tenant = _tenant(db_session)
    _enable_planner(db_session, tenant)
    tag = _trigger_tag(db_session)
    item = action_item_service.create(
        db_session, tenant.id, "Follow up on deposit",
        ai_instruction="Reply confirming the refund.", due_date=date(2020, 1, 1), due_time=time(9, 0), tag_ids=[tag.id],
    )
    db_session.commit()

    action_planner_trigger_service.run_due_action_planner_triggers(db_session)

    assert len(capture_planner) == 1
    call = capture_planner[0]
    assert call["tenant_id"] == tenant.id
    assert call["channel"] == "email"
    assert "Reply confirming the refund." in call["operator_note"]
    db_session.refresh(item)
    assert item.planner_triggered_at is not None
    assert db_session.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant.id).count() == 1


def test_general_tenantless_action_never_fires(db_session, capture_planner):
    tag = _trigger_tag(db_session)
    action_item_service.create_general(db_session, "General due task", due_date=date(2020, 1, 1), tag_ids=[tag.id])
    db_session.commit()

    action_planner_trigger_service.run_due_action_planner_triggers(db_session)

    assert capture_planner == []


def test_action_without_trigger_tag_does_not_fire(db_session, capture_planner):
    tenant = _tenant(db_session)
    _enable_planner(db_session, tenant)
    non_trigger = ActionTagDefinition(name="Plain", color="#000000", is_active=True, triggers_planner=False)
    db_session.add(non_trigger)
    db_session.commit()
    action_item_service.create(db_session, tenant.id, "Due but untagged", due_date=date(2020, 1, 1), tag_ids=[non_trigger.id])
    db_session.commit()

    action_planner_trigger_service.run_due_action_planner_triggers(db_session)

    assert capture_planner == []


def test_future_due_action_does_not_fire(db_session, capture_planner):
    tenant = _tenant(db_session)
    _enable_planner(db_session, tenant)
    tag = _trigger_tag(db_session)
    action_item_service.create(db_session, tenant.id, "Future task", due_date=date(2999, 1, 1), due_time=time(9, 0), tag_ids=[tag.id])
    db_session.commit()

    action_planner_trigger_service.run_due_action_planner_triggers(db_session)

    assert capture_planner == []


def test_already_triggered_action_does_not_refire(db_session, capture_planner):
    tenant = _tenant(db_session)
    _enable_planner(db_session, tenant)
    tag = _trigger_tag(db_session)
    item = action_item_service.create(db_session, tenant.id, "Once", due_date=date(2020, 1, 1), due_time=time(9, 0), tag_ids=[tag.id])
    item.planner_triggered_at = datetime.now(timezone.utc)
    db_session.commit()

    action_planner_trigger_service.run_due_action_planner_triggers(db_session)

    assert capture_planner == []


def test_no_conversation_history_leaves_item_unclaimed_for_retry(db_session, monkeypatch):
    tenant = _tenant(db_session)
    _enable_planner(db_session, tenant)
    tag = _trigger_tag(db_session)
    item = action_item_service.create(db_session, tenant.id, "No history", due_date=date(2020, 1, 1), due_time=time(9, 0), tag_ids=[tag.id])
    db_session.commit()

    calls = []
    monkeypatch.setattr(action_planner_trigger_service, "run_ai_plan_for_draft", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(action_planner_trigger_service, "compute_last_message_by_tenant_id", lambda db, tenant_ids: {})

    action_planner_trigger_service.run_due_action_planner_triggers(db_session)

    assert calls == []
    db_session.refresh(item)
    # Left unclaimed on purpose so a later sweep retries once the tenant gains a conversation.
    assert item.planner_triggered_at is None


def test_skipped_item_fires_on_later_sweep_once_history_exists(db_session, monkeypatch):
    tenant = _tenant(db_session)
    _enable_planner(db_session, tenant)
    tag = _trigger_tag(db_session)
    item = action_item_service.create(db_session, tenant.id, "Later", due_date=date(2020, 1, 1), due_time=time(9, 0), tag_ids=[tag.id])
    db_session.commit()

    calls = []
    monkeypatch.setattr(action_planner_trigger_service, "run_ai_plan_for_draft", lambda *a, **k: calls.append(k))

    # Tick 1: no conversation history yet - skipped, item stays unclaimed.
    monkeypatch.setattr(action_planner_trigger_service, "compute_last_message_by_tenant_id", lambda db, tenant_ids: {})
    action_planner_trigger_service.run_due_action_planner_triggers(db_session)
    assert calls == []
    db_session.refresh(item)
    assert item.planner_triggered_at is None

    # Tick 2: a conversation now exists - the same item fires and is claimed.
    monkeypatch.setattr(
        action_planner_trigger_service,
        "compute_last_message_by_tenant_id",
        lambda db, tenant_ids: {tid: (datetime.now(timezone.utc), "email", "inbound") for tid in tenant_ids},
    )
    action_planner_trigger_service.run_due_action_planner_triggers(db_session)
    assert len(calls) == 1
    db_session.refresh(item)
    assert item.planner_triggered_at is not None


def test_instruction_channel_overrides_last_message_channel(db_session, monkeypatch, capture_planner):
    """When the action's instruction names a channel, the planner drafts on it - not last in/out."""
    tenant = _tenant(db_session)
    # Last message is email (fixture), but the instruction asks for WhatsApp; enable WhatsApp drafting.
    db_session.add(
        TenantAiSettings(tenant_id=tenant.id, planner_mode="manual", auto_draft_email=True, auto_draft_whatsapp=True)
    )
    db_session.commit()
    tag = _trigger_tag(db_session)
    action_item_service.create(
        db_session, tenant.id, "Deposit",
        ai_instruction="Reply to the guest on WhatsApp.", due_date=date(2020, 1, 1), due_time=time(9, 0), tag_ids=[tag.id],
    )
    db_session.commit()

    monkeypatch.setattr(action_planner_trigger_service, "extract_instructed_channel", lambda item: "whatsapp")

    action_planner_trigger_service.run_due_action_planner_triggers(db_session)

    assert len(capture_planner) == 1
    assert capture_planner[0]["channel"] == "whatsapp"
    assert db_session.query(AiAutoDraft).filter(AiAutoDraft.channel == "whatsapp").count() == 1


def test_no_instruction_channel_falls_back_to_last_message_channel(db_session, capture_planner):
    """With no channel named in the instruction, the last-message channel is used (fixture: email)."""
    tenant = _tenant(db_session)
    _enable_planner(db_session, tenant)
    tag = _trigger_tag(db_session)
    action_item_service.create(
        db_session, tenant.id, "Deposit",
        ai_instruction="Confirm the refund amount.", due_date=date(2020, 1, 1), due_time=time(9, 0), tag_ids=[tag.id],
    )
    db_session.commit()

    action_planner_trigger_service.run_due_action_planner_triggers(db_session)

    assert len(capture_planner) == 1
    assert capture_planner[0]["channel"] == "email"


def test_extract_instructed_channel_reads_the_model_result(monkeypatch):
    item = ActionItem(title="x", ai_instruction="Please answer them over WhatsApp today.", source="manual")

    def fake_generate(prompt, *, response_schema=None, **kwargs):
        assert "WhatsApp" in prompt
        return gemini_client.GenerationResult(
            text="{}", parsed={"channel": "whatsapp"}, model="test", prompt_tokens=None, output_tokens=None, latency_ms=1,
        )

    monkeypatch.setattr(gemini_client, "generate", fake_generate)
    assert action_planner_trigger_service.extract_instructed_channel(item) == "whatsapp"


def test_extract_instructed_channel_skips_model_when_no_text(monkeypatch):
    item = ActionItem(title="x", ai_instruction=None, description=None, source="manual")

    def boom(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("Gemini must not be called when there is no instruction/description text")

    monkeypatch.setattr(gemini_client, "generate", boom)
    assert action_planner_trigger_service.extract_instructed_channel(item) is None


def test_extract_instructed_channel_falls_back_on_model_error(monkeypatch):
    item = ActionItem(title="x", ai_instruction="Reply on WhatsApp.", source="manual")

    def raise_error(*args, **kwargs):
        raise gemini_client.GeminiClientError("no api key")

    monkeypatch.setattr(gemini_client, "generate", raise_error)
    assert action_planner_trigger_service.extract_instructed_channel(item) is None


def test_extract_instructed_channel_none_result_returns_none(monkeypatch):
    item = ActionItem(title="x", description="Just follow up about the deposit.", source="manual")

    monkeypatch.setattr(
        gemini_client,
        "generate",
        lambda prompt, **kwargs: gemini_client.GenerationResult(
            text="{}", parsed={"channel": "none"}, model="test", prompt_tokens=None, output_tokens=None, latency_ms=1,
        ),
    )
    assert action_planner_trigger_service.extract_instructed_channel(item) is None


def test_missing_time_defaults_to_nine_local():
    item = ActionItem(title="x", due_date=date(2026, 6, 1), due_time=None, source="manual")
    due_utc = action_planner_trigger_service._due_instant_utc(item)
    # 09:00 Europe/Amsterdam in June (CEST, UTC+2) == 07:00 UTC.
    assert due_utc == datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc)
