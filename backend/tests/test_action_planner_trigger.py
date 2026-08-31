from datetime import date, datetime, time, timezone

import pytest

from app.models.action_item import ActionItem
from app.models.action_tag_definition import ActionTagDefinition
from app.models.ai_auto_draft import AiAutoDraft
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import action_item_service, action_planner_trigger_service


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


def test_missing_time_defaults_to_nine_local():
    item = ActionItem(title="x", due_date=date(2026, 6, 1), due_time=None, source="manual")
    due_utc = action_planner_trigger_service._due_instant_utc(item)
    # 09:00 Europe/Amsterdam in June (CEST, UTC+2) == 07:00 UTC.
    assert due_utc == datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc)
