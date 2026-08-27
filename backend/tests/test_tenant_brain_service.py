from datetime import datetime, timezone

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.ai_agent_profile import BRAIN_WRITER_ROLE, AiAgentProfile
from app.models.ai_agent_run import AiAgentRun
from app.models.action_writer_trigger import ActionWriterTrigger
from app.models.brain_field_definition import BrainFieldDefinition
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_brain_entry import TenantBrainEntry
from app.models.tenant_brain_entry_history import TenantBrainEntryHistory
from app.models.tenant_brain_field_value import TenantBrainFieldValue
from app.models.tenant_brain_trigger import TenantBrainTrigger
from app.models.user import User
from app.services import tenant_brain_service
from app.services import brain_field_service, datetime_placeholders
from app.services.tenant_brain_trigger_service import register_message_trigger
from app.services.action_writer_trigger_service import register_manual_trigger

REGULAR_USER = User(id=2, email="agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Brain Tenant", booking_id="B-brain-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


# --- add_entry / update_entry / delete_entry write correct history rows -------------------


def test_add_entry_writes_created_history(db_session):
    tenant = _create_tenant(db_session)
    entry = tenant_brain_service.add_entry(db_session, tenant, "Prefers late check-in", source="manual")
    db_session.commit()

    assert entry is not None
    assert entry.content == "Prefers late check-in"
    history = db_session.query(TenantBrainEntryHistory).filter(TenantBrainEntryHistory.entry_id == entry.id).one()
    assert history.action == "created"
    assert history.old_value is None
    assert history.new_value == "Prefers late check-in"


def test_add_entry_skips_blank_content(db_session):
    tenant = _create_tenant(db_session)
    entry = tenant_brain_service.add_entry(db_session, tenant, "   ", source="manual")
    assert entry is None


def test_update_entry_writes_updated_history_and_skips_noop(db_session):
    tenant = _create_tenant(db_session)
    entry = tenant_brain_service.add_entry(db_session, tenant, "Original", source="manual")
    db_session.commit()

    tenant_brain_service.update_entry(db_session, entry, "Original", changed_by_user_id=2)
    db_session.commit()
    assert db_session.query(TenantBrainEntryHistory).filter(TenantBrainEntryHistory.entry_id == entry.id).count() == 1

    tenant_brain_service.update_entry(db_session, entry, "Revised", changed_by_user_id=2)
    db_session.commit()

    assert entry.content == "Revised"
    history = (
        db_session.query(TenantBrainEntryHistory)
        .filter(TenantBrainEntryHistory.entry_id == entry.id, TenantBrainEntryHistory.action == "updated")
        .one()
    )
    assert history.old_value == "Original"
    assert history.new_value == "Revised"
    assert history.changed_by_user_id == 2


def test_delete_entry_writes_deleted_history_and_removes_row(db_session):
    tenant = _create_tenant(db_session)
    entry = tenant_brain_service.add_entry(db_session, tenant, "Will be deleted", source="manual")
    db_session.commit()
    entry_id = entry.id

    tenant_brain_service.delete_entry(db_session, entry, changed_by_user_id=2)
    db_session.commit()

    assert db_session.query(TenantBrainEntry).filter(TenantBrainEntry.id == entry_id).first() is None
    history = (
        db_session.query(TenantBrainEntryHistory)
        .filter(TenantBrainEntryHistory.entry_id == entry_id, TenantBrainEntryHistory.action == "deleted")
        .one()
    )
    assert history.old_value == "Will be deleted"
    assert history.new_value is None


# --- trigger registration: independent of planner_mode, gated on brain_writer_enabled -----


def test_no_trigger_when_brain_writer_disabled(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, brain_writer_enabled=False, planner_mode="auto-send"))
    db_session.commit()

    register_message_trigger(db_session, tenant_id=tenant.id, channel="email", direction="inbound")
    db_session.commit()

    assert db_session.query(TenantBrainTrigger).filter(TenantBrainTrigger.tenant_id == tenant.id).count() == 0


def test_no_trigger_when_no_ai_settings_row_exists(db_session):
    tenant = _create_tenant(db_session)
    register_message_trigger(db_session, tenant_id=tenant.id, channel="email", direction="inbound")
    db_session.commit()
    assert db_session.query(TenantBrainTrigger).count() == 0


def test_trigger_created_independent_of_planner_mode(db_session):
    tenant = _create_tenant(db_session)
    # planner_mode is "off" - brain-writing is still independently enabled.
    db_session.add(TenantAiSettings(tenant_id=tenant.id, brain_writer_enabled=True, planner_mode="off"))
    db_session.commit()

    register_message_trigger(db_session, tenant_id=tenant.id, channel="whatsapp", direction="inbound", whatsapp_endpoint_id=7)
    db_session.commit()

    trigger = db_session.query(TenantBrainTrigger).filter(TenantBrainTrigger.tenant_id == tenant.id).one()
    first_trigger_at = trigger.trigger_at
    assert trigger.channel == "whatsapp"
    assert trigger.whatsapp_endpoint_id == 7

    register_message_trigger(db_session, tenant_id=tenant.id, channel="whatsapp", direction="inbound", whatsapp_endpoint_id=7)
    db_session.commit()

    triggers = db_session.query(TenantBrainTrigger).filter(TenantBrainTrigger.tenant_id == tenant.id).all()
    assert len(triggers) == 1
    assert triggers[0].trigger_at >= first_trigger_at


def test_register_manual_trigger_uses_latest_communication_channel_and_upserts(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, action_writer_enabled=True))
    db_session.add(Communication(tenant_id=tenant.id, channel="email", direction="inbound", message="Earlier message", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    db_session.add(Communication(tenant_id=tenant.id, channel="whatsapp", direction="outbound", message="Later message", created_at=datetime(2026, 1, 2, tzinfo=timezone.utc)))
    db_session.commit()

    assert register_manual_trigger(db_session, tenant_id=tenant.id) is True
    db_session.commit()

    trigger = db_session.query(ActionWriterTrigger).filter(ActionWriterTrigger.tenant_id == tenant.id).one()
    assert trigger.channel == "whatsapp"
    first_trigger_at = trigger.trigger_at
    assert first_trigger_at <= datetime.now(timezone.utc).replace(tzinfo=None)

    assert register_manual_trigger(db_session, tenant_id=tenant.id) is True
    db_session.commit()

    triggers = db_session.query(ActionWriterTrigger).filter(ActionWriterTrigger.tenant_id == tenant.id).all()
    assert len(triggers) == 1
    assert triggers[0].trigger_at >= first_trigger_at


# --- generate_brain_update_for_trigger: LLM decision wiring --------------------------------


def _fake_generate(payload):
    from app.services import gemini_client

    def _generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(
            text="ignored", parsed=payload, model=model or "fake-model", prompt_tokens=1, output_tokens=1, latency_ms=1
        )

    return _generate


def _setup_brain_writer(db_session, tenant):
    profile = AiAgentProfile(name="Default Brain Writer", role=BRAIN_WRITER_ROLE, is_default=True)
    db_session.add(profile)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, brain_writer_enabled=True))
    db_session.commit()
    return profile


def test_generate_brain_update_adds_no_entries_when_should_remember_is_false(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_brain_writer(db_session, tenant)
    monkeypatch.setattr(tenant_brain_service.ai_agent_orchestrator, "latest_message_text", lambda db, tenant_id, channel: "What time is check-in?")
    monkeypatch.setattr(
        tenant_brain_service.gemini_client,
        "generate",
        _fake_generate({"should_remember": False, "entries": [], "reasoning": "Routine question."}),
    )
    trigger = TenantBrainTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    added = tenant_brain_service.generate_brain_update_for_trigger(db_session, trigger)
    db_session.commit()

    assert added == []
    assert db_session.query(TenantBrainEntry).filter(TenantBrainEntry.tenant_id == tenant.id).count() == 0
    run = db_session.query(AiAgentRun).filter(AiAgentRun.tenant_id == tenant.id).one()
    assert run.status == "skipped"


def test_generate_brain_update_resolves_datetime_placeholders_in_field_instructions(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_brain_writer(db_session, tenant)
    monkeypatch.setattr(tenant_brain_service.ai_agent_orchestrator, "latest_message_text", lambda db, tenant_id, channel: "Anything new?")
    fixed_now = datetime(2026, 8, 27, 9, 8, 7, tzinfo=timezone.utc)
    monkeypatch.setattr(datetime_placeholders, "_now", lambda: fixed_now)

    definition = brain_field_service.add_definition(
        db_session,
        key="arrival",
        label="Arrival",
        ai_instruction="Look for updates on {{current_date}}.",
    )
    db_session.commit()

    captured_prompt = {}

    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        from app.services import gemini_client

        captured_prompt["prompt"] = prompt
        return gemini_client.GenerationResult(
            text="ignored",
            parsed={"should_remember": False, "entries": [], "reasoning": "No durable info."},
            model=model or "fake-model",
            prompt_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    monkeypatch.setattr(tenant_brain_service.gemini_client, "generate", fake_generate)

    trigger = TenantBrainTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    added = tenant_brain_service.generate_brain_update_for_trigger(db_session, trigger)
    db_session.commit()

    assert added == []
    assert definition.ai_instruction == "Look for updates on {{current_date}}."
    assert f"look for: Look for updates on {fixed_now.date().isoformat()}." in captured_prompt["prompt"]
    assert "{{current_date}}" not in captured_prompt["prompt"]

def test_generate_brain_update_adds_entries_when_should_remember_is_true(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_brain_writer(db_session, tenant)
    monkeypatch.setattr(tenant_brain_service.ai_agent_orchestrator, "latest_message_text", lambda db, tenant_id, channel: "I'm allergic to feathers, please no feather pillows.")
    monkeypatch.setattr(
        tenant_brain_service.gemini_client,
        "generate",
        _fake_generate(
            {"should_remember": True, "entries": ["Allergic to feathers - no feather pillows."], "reasoning": "Durable allergy info."}
        ),
    )
    trigger = TenantBrainTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    added = tenant_brain_service.generate_brain_update_for_trigger(db_session, trigger)
    db_session.commit()

    assert len(added) == 1
    assert added[0].content == "Allergic to feathers - no feather pillows."
    assert added[0].source == "planner"
    run = db_session.query(AiAgentRun).filter(AiAgentRun.tenant_id == tenant.id).one()
    assert run.status == "completed"
    assert run.mode == "brain_writer"


def test_generate_brain_update_noop_when_disabled(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, brain_writer_enabled=False))
    db_session.commit()
    trigger = TenantBrainTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc))

    added = tenant_brain_service.generate_brain_update_for_trigger(db_session, trigger)

    assert added == []
    assert db_session.query(AiAgentRun).filter(AiAgentRun.tenant_id == tenant.id).count() == 0


# --- API routes ------------------------------------------------------------------------


def test_brain_routes_add_edit_delete_and_history(user_client, db_session):
    tenant = _create_tenant(db_session)

    create_response = user_client.post(f"/api/tenants/{tenant.id}/brain", json={"content": "Likes ground floor rooms"})
    assert create_response.status_code == 201
    entry_id = create_response.json()["id"]
    assert create_response.json()["source"] == "manual"

    list_response = user_client.get(f"/api/tenants/{tenant.id}/brain")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    patch_response = user_client.patch(f"/api/tenants/{tenant.id}/brain/{entry_id}", json={"content": "Likes top floor rooms"})
    assert patch_response.status_code == 200
    assert patch_response.json()["content"] == "Likes top floor rooms"

    delete_response = user_client.delete(f"/api/tenants/{tenant.id}/brain/{entry_id}")
    assert delete_response.status_code == 204

    history_response = user_client.get(f"/api/tenants/{tenant.id}/brain/history")
    assert history_response.status_code == 200
    actions = [row["action"] for row in history_response.json()]
    assert actions == ["deleted", "updated", "created"]


def test_scan_endpoint_adds_entries_from_scanner(user_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_brain_writer(db_session, tenant)
    monkeypatch.setattr(
        tenant_brain_service.gemini_client,
        "generate",
        _fake_generate({"should_remember": True, "entries": ["Always pays by card."], "reasoning": "Payment preference."}),
    )

    response = user_client.post(f"/api/tenants/{tenant.id}/brain/scan")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["source"] == "scanner"


def test_scan_endpoint_registers_action_writer_trigger_only_after_repeat_scan(user_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_brain_writer(db_session, tenant)
    settings = db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).one()
    settings.action_writer_enabled = True
    db_session.add(Communication(tenant_id=tenant.id, channel="email", direction="inbound", message="Hello there"))
    db_session.commit()

    monkeypatch.setattr(
        tenant_brain_service.gemini_client,
        "generate",
        _fake_generate({"should_remember": True, "entries": ["Always pays by card."], "reasoning": "Payment preference."}),
    )

    first_response = user_client.post(f"/api/tenants/{tenant.id}/brain/scan")
    assert first_response.status_code == 200
    assert db_session.query(ActionWriterTrigger).filter(ActionWriterTrigger.tenant_id == tenant.id).count() == 0

    second_response = user_client.post(f"/api/tenants/{tenant.id}/brain/scan")
    assert second_response.status_code == 200
    trigger = db_session.query(ActionWriterTrigger).filter(ActionWriterTrigger.tenant_id == tenant.id).one()
    assert trigger.channel == "email"
    assert trigger.trigger_at <= datetime.now(timezone.utc).replace(tzinfo=None)


def test_scan_endpoint_does_not_register_action_writer_trigger_when_disabled(user_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _setup_brain_writer(db_session, tenant)
    db_session.add(Communication(tenant_id=tenant.id, channel="email", direction="inbound", message="Hello there"))
    db_session.commit()

    monkeypatch.setattr(
        tenant_brain_service.gemini_client,
        "generate",
        _fake_generate({"should_remember": True, "entries": ["Always pays by card."], "reasoning": "Payment preference."}),
    )

    user_client.post(f"/api/tenants/{tenant.id}/brain/scan")
    user_client.post(f"/api/tenants/{tenant.id}/brain/scan")

    assert db_session.query(ActionWriterTrigger).filter(ActionWriterTrigger.tenant_id == tenant.id).count() == 0


