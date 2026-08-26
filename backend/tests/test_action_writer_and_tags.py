from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.action_item import ActionItem
from app.models.action_item_tag import ActionItemTag
from app.models.action_tag_definition import ActionTagDefinition
from app.models.action_writer_trigger import ActionWriterTrigger
from app.models.ai_agent_profile import ACTION_WRITER_ROLE, AiAgentProfile
from app.models.ai_agent_run import AiAgentRun
from app.models.memory_suggestion import MemorySuggestion
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.user import User
from app.services import action_item_service, action_writer_service

REGULAR_USER = User(id=3, email="actions@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Action Tenant", booking_id="B-action-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


# --- Action tags API ------------------------------------------------------------------------


def test_create_list_update_delete_action_tag(user_client, db_session):
    create_response = user_client.post("/api/action-tags", json={"name": "Follow-up", "color": "#0891b2"})
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["name"] == "Follow-up"
    assert body["is_active"] is True
    tag_id = body["id"]

    list_response = user_client.get("/api/action-tags")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    patch_response = user_client.patch(f"/api/action-tags/{tag_id}", json={"color": "#f43f5e"})
    assert patch_response.status_code == 200
    assert patch_response.json()["color"] == "#f43f5e"

    delete_response = user_client.delete(f"/api/action-tags/{tag_id}")
    assert delete_response.status_code == 204
    assert db_session.query(ActionTagDefinition).count() == 0


def test_create_action_tag_rejects_duplicate_name(user_client):
    user_client.post("/api/action-tags", json={"name": "Billing", "color": "#000000"})
    response = user_client.post("/api/action-tags", json={"name": "Billing", "color": "#111111"})
    assert response.status_code == 409


def test_list_active_only_excludes_inactive_tags(user_client):
    create_response = user_client.post("/api/action-tags", json={"name": "Archived", "color": "#000000"})
    tag_id = create_response.json()["id"]
    user_client.patch(f"/api/action-tags/{tag_id}", json={"is_active": False})

    response = user_client.get("/api/action-tags", params={"active_only": True})
    assert response.status_code == 200
    assert response.json() == []


# --- Action item tag/priority threading, and recurrence-on-complete ------------------------


def test_action_item_read_includes_tags(user_client, db_session):
    tenant = _create_tenant(db_session)
    tag_a = ActionTagDefinition(name="Urgent", color="#f43f5e")
    tag_b = ActionTagDefinition(name="Guest", color="#0ea5e9")
    db_session.add_all([tag_a, tag_b])
    db_session.commit()

    response = user_client.post(
        f"/api/tenants/{tenant.id}/action-items",
        json={"title": "Call guest", "tag_ids": [tag_a.id, tag_b.id], "priority": "p1"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["tags"] == [
        {"id": tag_a.id, "name": "Urgent", "color": "#f43f5e"},
        {"id": tag_b.id, "name": "Guest", "color": "#0ea5e9"},
    ]
    assert body["priority"] == "p1"


def test_create_action_item_persists_multiple_tags_in_order(user_client, db_session):
    tenant = _create_tenant(db_session)
    tag_a = ActionTagDefinition(name="Urgent", color="#f43f5e")
    tag_b = ActionTagDefinition(name="Guest", color="#0ea5e9")
    db_session.add_all([tag_a, tag_b])
    db_session.commit()

    response = user_client.post(
        f"/api/tenants/{tenant.id}/action-items",
        json={"title": "Call guest", "tag_ids": [tag_a.id, tag_b.id]},
    )
    assert response.status_code == 201
    item_id = response.json()["id"]

    rows = db_session.query(ActionItemTag).filter(ActionItemTag.action_item_id == item_id).order_by(ActionItemTag.position, ActionItemTag.id).all()
    assert [row.tag_id for row in rows] == [tag_a.id, tag_b.id]
    assert [row.position for row in rows] == [0, 1]


def test_update_action_item_tag_ids_replace_clear_and_preserve(user_client, db_session):
    tenant = _create_tenant(db_session)
    tag_a = ActionTagDefinition(name="A", color="#111111")
    tag_b = ActionTagDefinition(name="B", color="#222222")
    tag_c = ActionTagDefinition(name="C", color="#333333")
    db_session.add_all([tag_a, tag_b, tag_c])
    db_session.commit()
    item = action_item_service.create(db_session, tenant.id, "Original title", due_date=date(2026, 8, 1), tag_ids=[tag_a.id, tag_b.id], priority="p3")
    db_session.commit()

    response = user_client.patch(f"/api/action-items/{item.id}", json={"tag_ids": [tag_b.id, tag_c.id]})
    assert response.status_code == 200
    assert [tag["id"] for tag in response.json()["tags"]] == [tag_b.id, tag_c.id]

    response = user_client.patch(
        f"/api/action-items/{item.id}",
        json={"title": "Retitled", "due_date": "2026-08-10", "priority": "p1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Retitled"
    assert body["due_date"] == "2026-08-10"
    assert body["priority"] == "p1"
    assert [tag["id"] for tag in body["tags"]] == [tag_b.id, tag_c.id]

    response = user_client.patch(f"/api/action-items/{item.id}", json={"tag_ids": []})
    assert response.status_code == 200
    assert response.json()["tags"] == []


def test_complete_recurring_item_creates_next_occurrence(db_session):
    tenant = _create_tenant(db_session)
    tag_a = ActionTagDefinition(name="Urgent", color="#f43f5e")
    tag_b = ActionTagDefinition(name="Guest", color="#0ea5e9")
    db_session.add_all([tag_a, tag_b])
    db_session.commit()
    item = action_item_service.create(
        db_session,
        tenant.id,
        "Check the boiler",
        due_date=date(2026, 8, 1),
        recurrence_interval_days=7,
        recurrence_anchor="due_date",
        tag_ids=[tag_a.id, tag_b.id],
    )
    db_session.commit()

    action_item_service.complete(db_session, item)
    db_session.commit()

    assert item.status == "done"
    next_item = db_session.query(ActionItem).filter(ActionItem.tenant_id == tenant.id, ActionItem.status == "open").one()
    assert next_item.title == "Check the boiler"
    assert next_item.due_date == date(2026, 8, 8)
    assert next_item.recurrence_interval_days == 7
    assert next_item.tag_ids == [tag_a.id, tag_b.id]


def test_complete_non_recurring_item_creates_no_next_occurrence(db_session):
    tenant = _create_tenant(db_session)
    item = action_item_service.create(db_session, tenant.id, "One-off task")
    db_session.commit()

    action_item_service.complete(db_session, item)
    db_session.commit()

    assert db_session.query(ActionItem).filter(ActionItem.tenant_id == tenant.id).count() == 1


def test_list_open_categorized_buckets_by_due_date_boundaries(db_session):
    tenant = _create_tenant(db_session)
    today = date.today()
    overdue = action_item_service.create(db_session, tenant.id, "Overdue", due_date=today - timedelta(days=1))
    today_item = action_item_service.create(db_session, tenant.id, "Today", due_date=today)
    tomorrow = action_item_service.create(db_session, tenant.id, "Tomorrow", due_date=today + timedelta(days=1))
    upcoming = action_item_service.create(db_session, tenant.id, "Upcoming", due_date=today + timedelta(days=2))
    edge = action_item_service.create(db_session, tenant.id, "Edge", due_date=today + timedelta(days=7))
    excluded = action_item_service.create(db_session, tenant.id, "Excluded", due_date=today + timedelta(days=8))
    no_due = action_item_service.create(db_session, tenant.id, "No due")
    db_session.commit()

    buckets = action_item_service.list_open_categorized(db_session)

    assert [item.title for item in buckets.overdue] == ["Overdue"]
    assert [item.title for item in buckets.today] == ["Today"]
    assert [item.title for item in buckets.tomorrow] == ["Tomorrow"]
    assert [item.title for item in buckets.upcoming] == ["Upcoming", "Edge"]
    assert excluded not in buckets.overdue + buckets.today + buckets.tomorrow + buckets.upcoming
    assert no_due not in buckets.overdue + buckets.today + buckets.tomorrow + buckets.upcoming


def test_create_general_action_item_and_nullable_tenant_id(db_session):
    general_item = action_item_service.create_general(db_session, "General follow-up", due_date=date(2026, 8, 27), priority="p2", created_by_user_id=7)
    explicit_none_item = action_item_service.create(db_session, None, "Explicit none")
    db_session.commit()

    assert general_item is not None
    assert general_item.tenant_id is None
    assert general_item.created_by_user_id == 7
    assert explicit_none_item is not None
    assert explicit_none_item.tenant_id is None


# --- action_writer_service: creation automatic, modify/delete gated on approval ------------


def _fake_generate(payload):
    from app.services import gemini_client

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(
            text="ignored", parsed=payload, model=model or "fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    return _generate


def _setup_action_writer(db_session, tenant):
    profile = AiAgentProfile(name="Default Action Writer", role=ACTION_WRITER_ROLE, is_default=True)
    db_session.add(profile)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, action_writer_enabled=True))
    db_session.commit()
    return profile


def test_action_writer_creates_new_item_directly(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_action_writer(db_session, tenant)
    tag_a = ActionTagDefinition(name="Invoice", color="#0891b2")
    tag_b = ActionTagDefinition(name="Follow-up", color="#f97316")
    db_session.add_all([tag_a, tag_b])
    db_session.commit()
    monkeypatch.setattr(action_writer_service.ai_agent_orchestrator, "latest_message_text", lambda db, tenant_id, channel: "Please call me back about the invoice.")
    monkeypatch.setattr(
        action_writer_service.gemini_client,
        "generate",
        _fake_generate({"new_items": [{"title": "Call tenant about invoice", "tags": ["Invoice", "Follow-up"]}], "reasoning": "Explicit callback request."}),
    )
    trigger = ActionWriterTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    action_writer_service.generate_action_writer_update_for_trigger(db_session, trigger)
    db_session.commit()

    item = db_session.query(ActionItem).filter(ActionItem.tenant_id == tenant.id).one()
    assert item.title == "Call tenant about invoice"
    assert item.source == "ai"
    assert item.status == "open"
    assert item.tag_ids == [tag_a.id, tag_b.id]
    run = db_session.query(AiAgentRun).filter(AiAgentRun.tenant_id == tenant.id).one()
    assert run.status == "completed"
    assert run.mode == "action_writer"


def test_action_writer_includes_payments_context_when_enabled(db_session, monkeypatch):
    """include_payments exists on AiAgentProfile and is honored by the planner/drafter, but was
    never wired into the action writer's own prompt builder -- toggling it on for an
    action_writer profile must actually include payments/charges context in its prompt."""
    from app.models.finance import Finance

    tenant = _create_tenant(db_session)
    profile = _setup_action_writer(db_session, tenant)
    profile.include_payments = True
    db_session.add(Finance(tenant_id=tenant.id, type="charge", amount=120, currency="EUR", description="Cleaning fee"))
    db_session.commit()

    captured_prompts = []
    monkeypatch.setattr(action_writer_service.ai_agent_orchestrator, "latest_message_text", lambda db, tenant_id, channel: "When is my next payment due?")

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        from app.services import gemini_client

        captured_prompts.append(prompt)
        return gemini_client.GenerationResult(
            text="ignored", parsed={"reasoning": "No action needed."}, model=model or "fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    monkeypatch.setattr(action_writer_service.gemini_client, "generate", _generate)
    trigger = ActionWriterTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    action_writer_service.generate_action_writer_update_for_trigger(db_session, trigger)
    db_session.commit()

    assert len(captured_prompts) == 1
    assert "Cleaning fee" in captured_prompts[0]


def test_action_writer_modify_creates_pending_suggestion_not_direct_change(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_action_writer(db_session, tenant)
    old_tag_a = ActionTagDefinition(name="Old A", color="#111111")
    old_tag_b = ActionTagDefinition(name="Old B", color="#222222")
    new_tag_a = ActionTagDefinition(name="New A", color="#333333")
    new_tag_b = ActionTagDefinition(name="New B", color="#444444")
    db_session.add_all([old_tag_a, old_tag_b, new_tag_a, new_tag_b])
    db_session.commit()
    existing = action_item_service.create(db_session, tenant.id, "Original title", due_date=date(2026, 8, 1), tag_ids=[old_tag_a.id, old_tag_b.id])
    db_session.commit()

    monkeypatch.setattr(action_writer_service.ai_agent_orchestrator, "latest_message_text", lambda db, tenant_id, channel: "Actually, push that back a week.")
    monkeypatch.setattr(
        action_writer_service.gemini_client,
        "generate",
        _fake_generate(
            {
                "modify_items": [
                    {
                        "action_item_id": existing.id,
                        "due_date": "2026-08-08",
                        "tags": ["New A", "New B"],
                        "reasoning": "Guest asked to push it back.",
                    }
                ],
                "reasoning": "Due date change requested.",
            }
        ),
    )
    trigger = ActionWriterTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    action_writer_service.generate_action_writer_update_for_trigger(db_session, trigger)
    db_session.commit()

    # The existing item is untouched - only a pending suggestion was created.
    db_session.refresh(existing)
    assert existing.due_date == date(2026, 8, 1)
    suggestion = db_session.query(MemorySuggestion).filter(MemorySuggestion.kind == "action_item_modify").one()
    assert suggestion.target_id == existing.id
    assert suggestion.status == "pending"
    assert suggestion.tenant_id == tenant.id
    assert suggestion.proposed_value["due_date"] == "2026-08-08"
    assert suggestion.proposed_value["tag_ids"] == [new_tag_a.id, new_tag_b.id]


def test_action_writer_delete_creates_pending_suggestion(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_action_writer(db_session, tenant)
    existing = action_item_service.create(db_session, tenant.id, "No longer needed")
    db_session.commit()

    monkeypatch.setattr(action_writer_service.ai_agent_orchestrator, "latest_message_text", lambda db, tenant_id, channel: "Never mind, forget that task.")
    monkeypatch.setattr(
        action_writer_service.gemini_client,
        "generate",
        _fake_generate({"delete_items": [{"action_item_id": existing.id, "reasoning": "Guest withdrew the request."}], "reasoning": "No longer needed."}),
    )
    trigger = ActionWriterTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    action_writer_service.generate_action_writer_update_for_trigger(db_session, trigger)
    db_session.commit()

    db_session.refresh(existing)
    assert existing.status == "open"
    suggestion = db_session.query(MemorySuggestion).filter(MemorySuggestion.kind == "action_item_delete").one()
    assert suggestion.target_id == existing.id
    assert suggestion.status == "pending"


def test_action_writer_complete_creates_pending_suggestion(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_action_writer(db_session, tenant)
    existing = action_item_service.create(db_session, tenant.id, "Completed task")
    db_session.commit()

    monkeypatch.setattr(action_writer_service.ai_agent_orchestrator, "latest_message_text", lambda db, tenant_id, channel: "Done, that's handled.")
    monkeypatch.setattr(
        action_writer_service.gemini_client,
        "generate",
        _fake_generate({"complete_items": [{"action_item_id": existing.id, "reasoning": "Tenant said it was finished."}], "reasoning": "Task completed."}),
    )
    trigger = ActionWriterTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    action_writer_service.generate_action_writer_update_for_trigger(db_session, trigger)
    db_session.commit()

    db_session.refresh(existing)
    assert existing.status == "open"
    suggestion = db_session.query(MemorySuggestion).filter(MemorySuggestion.kind == "action_item_complete").one()
    assert suggestion.target_id == existing.id
    assert suggestion.status == "pending"


def test_action_writer_does_not_duplicate_pending_suggestion_on_repeat_trigger(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_action_writer(db_session, tenant)
    existing = action_item_service.create(db_session, tenant.id, "Original title")
    db_session.commit()

    monkeypatch.setattr(action_writer_service.ai_agent_orchestrator, "latest_message_text", lambda db, tenant_id, channel: "Push it back.")
    monkeypatch.setattr(
        action_writer_service.gemini_client,
        "generate",
        _fake_generate({"modify_items": [{"action_item_id": existing.id, "title": "Updated title", "reasoning": "x"}], "reasoning": "y"}),
    )

    for _ in range(2):
        trigger = ActionWriterTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))
        action_writer_service.generate_action_writer_update_for_trigger(db_session, trigger)
        db_session.commit()

    assert db_session.query(MemorySuggestion).filter(MemorySuggestion.kind == "action_item_modify").count() == 1


def test_action_writer_noop_when_disabled(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, action_writer_enabled=False))
    db_session.commit()
    trigger = ActionWriterTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    action_writer_service.generate_action_writer_update_for_trigger(db_session, trigger)

    assert db_session.query(AiAgentRun).filter(AiAgentRun.tenant_id == tenant.id).count() == 0


# --- memory_suggestion_service apply handlers for action item kinds ------------------------


def test_approve_action_item_modify_suggestion_applies_change(db_session):
    from app.services import memory_suggestion_service

    tenant = _create_tenant(db_session)
    item = action_item_service.create(db_session, tenant.id, "Original title")
    db_session.commit()
    suggestion = MemorySuggestion(
        kind="action_item_modify", tenant_id=tenant.id, target_id=item.id, proposed_value={"title": "New title"}, status="pending"
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion, reviewer_id=None)
    db_session.commit()

    assert result.applied is True
    db_session.refresh(item)
    assert item.title == "New title"


def test_approve_action_item_modify_suggestion_applies_tag_changes(db_session):
    from app.services import memory_suggestion_service

    tenant = _create_tenant(db_session)
    old_tag = ActionTagDefinition(name="Old", color="#111111")
    new_tag_a = ActionTagDefinition(name="New A", color="#222222")
    new_tag_b = ActionTagDefinition(name="New B", color="#333333")
    db_session.add_all([old_tag, new_tag_a, new_tag_b])
    db_session.commit()
    item = action_item_service.create(db_session, tenant.id, "Original title", tag_ids=[old_tag.id])
    db_session.commit()
    suggestion = MemorySuggestion(
        kind="action_item_modify",
        tenant_id=tenant.id,
        target_id=item.id,
        proposed_value={"tag_ids": [new_tag_a.id, new_tag_b.id]},
        status="pending",
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion, reviewer_id=None)
    db_session.commit()

    assert result.applied is True
    db_session.refresh(item)
    assert item.tag_ids == [new_tag_a.id, new_tag_b.id]


def test_approve_action_item_delete_suggestion_dismisses_item(db_session):
    from app.services import memory_suggestion_service

    tenant = _create_tenant(db_session)
    item = action_item_service.create(db_session, tenant.id, "To be removed")
    db_session.commit()
    suggestion = MemorySuggestion(kind="action_item_delete", tenant_id=tenant.id, target_id=item.id, proposed_value={}, status="pending")
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion, reviewer_id=None)
    db_session.commit()

    assert result.applied is True
    db_session.refresh(item)
    assert item.status == "dismissed"


def test_approve_action_item_complete_suggestion_marks_item_done(db_session):
    from app.services import memory_suggestion_service

    tenant = _create_tenant(db_session)
    item = action_item_service.create(db_session, tenant.id, "Already done")
    db_session.commit()
    suggestion = MemorySuggestion(kind="action_item_complete", tenant_id=tenant.id, target_id=item.id, proposed_value={}, status="pending")
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion, reviewer_id=None)
    db_session.commit()

    assert result.applied is True
    db_session.refresh(item)
    assert item.status == "done"


def test_approve_action_item_modify_fails_gracefully_when_item_already_dismissed(db_session):
    from app.services import memory_suggestion_service

    tenant = _create_tenant(db_session)
    item = action_item_service.create(db_session, tenant.id, "Already gone")
    action_item_service.dismiss(db_session, item)
    db_session.commit()
    suggestion = MemorySuggestion(
        kind="action_item_modify", tenant_id=tenant.id, target_id=item.id, proposed_value={"title": "New"}, status="pending"
    )
    db_session.add(suggestion)
    db_session.commit()

    result = memory_suggestion_service.approve(db_session, suggestion, reviewer_id=None)

    assert result.applied is False


# --- quick natural-language add endpoint ----------------------------------------------------


def test_parse_action_item_text_endpoint(user_client, db_session, monkeypatch):
    from app.services import action_item_parse_service, gemini_client

    tenant = _create_tenant(db_session)

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(
            text="ignored", parsed={"title": "Call guest", "due_date": "2026-08-05", "priority": "p2"}, model="fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    monkeypatch.setattr(action_item_parse_service.gemini_client, "generate", fake_generate)

    response = user_client.post(f"/api/tenants/{tenant.id}/action-items/parse", json={"text": "Call guest next Wednesday"})

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Call guest"
    assert body["due_date"] == "2026-08-05"
    assert body["priority"] == "p2"


def test_parse_general_action_item_text_endpoint(user_client, db_session, monkeypatch):
    from app.services import action_item_parse_service, gemini_client

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(
            text="ignored", parsed={"title": "General task", "due_date": "2026-08-09", "priority": "p3"}, model="fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    monkeypatch.setattr(action_item_parse_service.gemini_client, "generate", fake_generate)

    response = user_client.post("/api/action-items/parse", json={"text": "General task next Sunday"})

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "General task"
    assert body["due_date"] == "2026-08-09"
    assert body["priority"] == "p3"


def test_create_general_action_item_endpoint_and_get_action_items_handles_null_tenant(user_client, db_session):
    create_response = user_client.post("/api/action-items", json={"title": "General item", "due_date": "2026-08-10", "priority": "p2"})
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["tenant_id"] is None
    assert body["tenant_name"] is None
    assert body["title"] == "General item"

    get_response = user_client.get("/api/action-items")
    assert get_response.status_code == 200
    rows = get_response.json()
    assert any(row["tenant_id"] is None and row["title"] == "General item" for row in rows)


# --- Dedicated action-item pending-suggestions review surface ------------------------------


def test_pending_suggestions_endpoint_returns_modify_diff_with_old_and_new(user_client, db_session):
    tenant = _create_tenant(db_session)
    old_tag_a = ActionTagDefinition(name="Old Tag A", color="#111111")
    old_tag_b = ActionTagDefinition(name="Old Tag B", color="#222222")
    new_tag_a = ActionTagDefinition(name="New Tag A", color="#333333")
    new_tag_b = ActionTagDefinition(name="New Tag B", color="#444444")
    db_session.add_all([old_tag_a, old_tag_b, new_tag_a, new_tag_b])
    db_session.commit()
    item = action_item_service.create(db_session, tenant.id, "Original title", due_date=date(2026, 8, 1), tag_ids=[old_tag_a.id, old_tag_b.id], priority="p3")
    db_session.commit()
    suggestion = MemorySuggestion(
        kind="action_item_modify",
        tenant_id=tenant.id,
        target_id=item.id,
        proposed_value={"title": "New title", "due_date": "2026-08-08", "priority": "p1", "tag_ids": [new_tag_a.id, new_tag_b.id]},
        reasoning="Guest asked to push it back and bump urgency.",
        status="pending",
    )
    db_session.add(suggestion)
    db_session.commit()

    response = user_client.get("/api/action-items/pending-suggestions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    row = body[0]
    assert row["kind"] == "action_item_modify"
    assert row["tenant_id"] == tenant.id
    assert row["action_item_id"] == item.id
    assert row["current"] == {
        "title": "Original title",
        "description": None,
        "due_date": "2026-08-01",
        "priority": "p3",
        "tags": [
            {"id": old_tag_a.id, "name": "Old Tag A", "color": "#111111"},
            {"id": old_tag_b.id, "name": "Old Tag B", "color": "#222222"},
        ],
        "status": "open",
    }
    assert row["proposed"]["title"] == "New title"
    assert row["proposed"]["due_date"] == "2026-08-08"
    assert row["proposed"]["priority"] == "p1"
    assert row["proposed"]["tag_ids"] == [new_tag_a.id, new_tag_b.id]
    assert row["proposed"]["tag_names"] == ["New Tag A", "New Tag B"]
    assert row["reasoning"] == "Guest asked to push it back and bump urgency."


def test_pending_suggestions_endpoint_returns_delete_with_deleted_flag(user_client, db_session):
    tenant = _create_tenant(db_session)
    item = action_item_service.create(db_session, tenant.id, "No longer needed")
    db_session.commit()
    suggestion = MemorySuggestion(kind="action_item_delete", tenant_id=tenant.id, target_id=item.id, proposed_value={}, status="pending")
    db_session.add(suggestion)
    db_session.commit()

    response = user_client.get("/api/action-items/pending-suggestions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["kind"] == "action_item_delete"
    assert body[0]["proposed"] == {"deleted": True}
    assert body[0]["current"]["title"] == "No longer needed"


def test_pending_suggestions_endpoint_returns_complete_with_completed_flag(user_client, db_session):
    tenant = _create_tenant(db_session)
    item = action_item_service.create(db_session, tenant.id, "Finished task")
    db_session.commit()
    suggestion = MemorySuggestion(kind="action_item_complete", tenant_id=tenant.id, target_id=item.id, proposed_value={}, status="pending")
    db_session.add(suggestion)
    db_session.commit()

    response = user_client.get("/api/action-items/pending-suggestions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["kind"] == "action_item_complete"
    assert body[0]["proposed"] == {"completed": True}
    assert body[0]["current"]["title"] == "Finished task"


def test_pending_suggestions_endpoint_excludes_non_action_item_kinds(user_client, db_session):
    tenant = _create_tenant(db_session)
    db_session.add(MemorySuggestion(kind="brain_entry", tenant_id=tenant.id, target_id=None, proposed_value={"content": "x"}, status="pending"))
    db_session.commit()

    response = user_client.get("/api/action-items/pending-suggestions")

    assert response.status_code == 200
    assert response.json() == []


def test_generic_suggestions_endpoint_excludes_action_item_kinds(user_client, db_session):
    tenant = _create_tenant(db_session)
    item = action_item_service.create(db_session, tenant.id, "Title")
    db_session.commit()
    db_session.add_all(
        [
            MemorySuggestion(kind="action_item_modify", tenant_id=tenant.id, target_id=item.id, proposed_value={"title": "New"}, status="pending"),
            MemorySuggestion(kind="action_item_complete", tenant_id=tenant.id, target_id=item.id, proposed_value={}, status="pending"),
            MemorySuggestion(kind="brain_entry", tenant_id=tenant.id, target_id=None, proposed_value={"content": "durable fact"}, status="pending"),
        ]
    )
    db_session.commit()

    response = user_client.get("/api/memory-suggestions")

    assert response.status_code == 200
    kinds = {row["kind"] for row in response.json()}
    assert kinds == {"brain_entry"}


def test_parse_action_item_text_returns_502_on_gemini_failure(user_client, db_session, monkeypatch):
    from app.services import action_item_parse_service, gemini_client

    tenant = _create_tenant(db_session)

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        raise gemini_client.GeminiClientError("boom")

    monkeypatch.setattr(action_item_parse_service.gemini_client, "generate", fake_generate)

    response = user_client.post(f"/api/tenants/{tenant.id}/action-items/parse", json={"text": "Call guest tomorrow"})

    assert response.status_code == 502
