"""Covers the settings-backup export/import router and its underlying service:
- secrets (the OneDrive refresh token) are never exported
- schema-version validation rejects bad/incompatible files with no writes
- a global dataset (ai_agent_profiles) round-trips byte-for-byte through export -> edit -> import replace
- a scoped dataset (tenant_ai_settings) merges by natural key and skips rows with a missing owner
- self-referential brain_sections (parent/child) survive a replace import without an FK ordering error
"""
import io
import json

import pytest

from app.models.admin_settings import AdminSettings
from app.models.ai_agent_profile import AiAgentProfile
from app.models.brain_section import BrainSection
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import settings_backup_service


@pytest.fixture(autouse=True)
def settings_backup_snapshot_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SETTINGS_BACKUP_SNAPSHOT_DIR", str(tmp_path / "settings-backups"))
    yield tmp_path


def _upload(client, mode, payload):
    body = json.dumps(payload).encode("utf-8")
    return client.post(
        "/api/settings-backup/import",
        params={"mode": mode},
        files={"file": ("backup.json", io.BytesIO(body), "application/json")},
    )


def test_export_excludes_onedrive_refresh_token(client, db_session):
    db_session.add(
        AdminSettings(
            id=1,
            onedrive_refresh_token_encrypted="super-secret-ciphertext",
            onedrive_drive_id="drive-123",
            onedrive_account_label="ops@example.com",
        )
    )
    db_session.commit()

    response = client.get("/api/settings-backup/export")
    assert response.status_code == 200
    payload = response.json()

    assert payload["schemaVersion"] == settings_backup_service.SCHEMA_VERSION
    assert "onedrive_refresh_token_encrypted" in payload["excludedFields"]["admin_settings"]
    admin_rows = payload["data"]["admin_settings"]
    assert len(admin_rows) == 1
    assert "onedrive_refresh_token_encrypted" not in admin_rows[0]
    # Non-secret sibling fields from the same migration are kept.
    assert admin_rows[0]["onedrive_drive_id"] == "drive-123"
    assert admin_rows[0]["onedrive_account_label"] == "ops@example.com"


def test_export_requires_admin(non_admin_client):
    response = non_admin_client.get("/api/settings-backup/export")
    assert response.status_code == 403


def test_import_rejects_missing_schema_version(client):
    response = _upload(client, "preview", {"data": {}})
    assert response.status_code == 400
    assert "schemaVersion" in response.json()["detail"]


def test_import_rejects_newer_schema_version(client):
    response = _upload(client, "preview", {"schemaVersion": 999, "data": {}})
    assert response.status_code == 400
    assert "999" in response.json()["detail"]


def test_import_rejects_invalid_json(client):
    response = client.post(
        "/api/settings-backup/import",
        params={"mode": "preview"},
        files={"file": ("backup.json", io.BytesIO(b"not json"), "application/json")},
    )
    assert response.status_code == 400


def test_preview_reports_counts_without_writing(client, db_session):
    db_session.add(AiAgentProfile(id=100, name="Existing planner", role="planner", instructions="old"))
    db_session.commit()

    export_response = client.get("/api/settings-backup/export")
    payload = export_response.json()
    payload["data"]["ai_agent_profiles"].append(
        {
            "id": 101,
            "name": "New drafter",
            "role": "drafter",
            "is_default": False,
            "is_active": True,
            "instructions": "new profile",
            "prompt_blocks": {},
            "model": None,
            "temperature": None,
            "max_output_tokens": None,
            "redo_model": None,
            "redo_temperature": None,
            "redo_max_output_tokens": None,
            "history_limit": 40,
            "history_channels": "both",
            "history_lookback_days": None,
            "include_beds24": True,
            "include_payments": False,
            "include_notes": True,
            "include_availability": False,
            "include_tenant_brain": False,
            "include_brain_index": True,
            "always_include_brain_sections": [],
            "match_inbound_language": True,
            "escalate_keywords": [],
            "on_no_template_match": "escalate",
            "min_confidence": 0.5,
            "max_redraft_attempts": 2,
            "block_auto_send_on_fail": True,
            "daily_token_cap": None,
            "created_by_user_id": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )

    preview_response = _upload(client, "preview", payload)
    assert preview_response.status_code == 200
    plan = preview_response.json()["datasets"]["ai_agent_profiles"]
    assert plan["replaced"] == 1
    assert plan["added"] == 1
    assert plan["removed"] == 0

    # A preview never writes.
    assert db_session.query(AiAgentProfile).count() == 1


def test_replace_round_trip_matches_export_byte_for_byte(client, db_session):
    db_session.add(AiAgentProfile(id=200, name="Planner v1", role="planner", instructions="Be concise."))
    db_session.commit()

    original_export = client.get("/api/settings-backup/export").json()

    # Mutate settings after the export, simulating live edits.
    profile = db_session.query(AiAgentProfile).filter(AiAgentProfile.id == 200).one()
    profile.instructions = "Be verbose instead."
    profile.name = "Planner v1 (edited)"
    db_session.add(AiAgentProfile(id=201, name="Extra profile", role="checker", instructions="temp"))
    db_session.commit()
    assert db_session.query(AiAgentProfile).count() == 2

    import_response = _upload(client, "replace", original_export)
    assert import_response.status_code == 200
    result = import_response.json()["datasets"]["ai_agent_profiles"]
    assert result["replaced"] == 1
    assert result["removed"] == 1

    db_session.expire_all()
    restored = db_session.query(AiAgentProfile).filter(AiAgentProfile.id == 200).one()
    assert restored.instructions == "Be concise."
    assert restored.name == "Planner v1"
    assert db_session.query(AiAgentProfile).count() == 1

    re_export = client.get("/api/settings-backup/export").json()
    assert re_export["data"]["ai_agent_profiles"] == original_export["data"]["ai_agent_profiles"]


def test_scoped_dataset_skips_row_with_missing_owner_tenant(client, db_session):
    tenant = Tenant(booking_id="B-1", name="Alice Guest")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    payload = {
        "schemaVersion": settings_backup_service.SCHEMA_VERSION,
        "exportedAt": "2026-01-01T00:00:00+00:00",
        "appVersion": None,
        "excludedFields": {},
        "data": {
            "tenant_ai_settings": [
                {
                    "id": 1,
                    "tenant_id": tenant.id,
                    "default_email_template_id": None,
                    "default_whatsapp_template_id": None,
                    "auto_draft_email": False,
                    "auto_draft_whatsapp": False,
                    "auto_send_email": False,
                    "auto_send_whatsapp": False,
                    "planner_mode": "manual",
                    "planner_profile_id": None,
                    "checker_profile_id": None,
                    "drafter_profile_id": None,
                    "brain_writer_enabled": False,
                    "brain_writer_profile_id": None,
                    "action_writer_enabled": False,
                    "action_writer_profile_id": None,
                    "formatter_enabled": False,
                    "formatter_profile_id": None,
                    "sales_manager_profile_id": None,
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": 2,
                    "tenant_id": 999999,
                    "default_email_template_id": None,
                    "default_whatsapp_template_id": None,
                    "auto_draft_email": False,
                    "auto_draft_whatsapp": False,
                    "auto_send_email": False,
                    "auto_send_whatsapp": False,
                    "planner_mode": "off",
                    "planner_profile_id": None,
                    "checker_profile_id": None,
                    "drafter_profile_id": None,
                    "brain_writer_enabled": False,
                    "brain_writer_profile_id": None,
                    "action_writer_enabled": False,
                    "action_writer_profile_id": None,
                    "formatter_enabled": False,
                    "formatter_profile_id": None,
                    "sales_manager_profile_id": None,
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            ]
        },
    }

    response = _upload(client, "merge", payload)
    assert response.status_code == 200
    result = response.json()["datasets"]["tenant_ai_settings"]
    assert result["added"] == 1
    assert result["skipped"] == 1
    assert "tenant_id=999999" in result["skipReasons"][0]

    db_session.expire_all()
    settings_rows = db_session.query(TenantAiSettings).all()
    assert len(settings_rows) == 1
    assert settings_rows[0].tenant_id == tenant.id

    # Merge never deletes: importing again with an empty file must not remove the row.
    empty_payload = {
        "schemaVersion": settings_backup_service.SCHEMA_VERSION,
        "exportedAt": "2026-01-01T00:00:00+00:00",
        "appVersion": None,
        "excludedFields": {},
        "data": {"tenant_ai_settings": []},
    }
    response = _upload(client, "merge", empty_payload)
    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.query(TenantAiSettings).count() == 1


def test_replace_import_from_older_export_does_not_blank_out_newer_columns(client, db_session):
    """An export taken before a later migration added a column (e.g. the Agent Instructions grid's
    instruction_sections) must not wipe that column back to its default when re-imported - the
    whole point of this backup is to undo a migration safely, not to erase it by re-importing an
    earlier snapshot."""
    existing = AiAgentProfile(
        id=300,
        name="Planner with grid",
        role="planner",
        instructions="Be concise.",
        instruction_sections=[{"id": "a", "label": "", "content": "Be concise.", "order": 0}],
    )
    db_session.add(existing)
    db_session.commit()

    old_shaped_export = {
        "schemaVersion": settings_backup_service.SCHEMA_VERSION,
        "exportedAt": "2026-01-01T00:00:00+00:00",
        "appVersion": None,
        "excludedFields": {},
        "data": {
            "ai_agent_profiles": [
                {
                    # No instruction_sections / instruction_canvas_notes keys at all - simulates a
                    # file exported before those columns existed.
                    "id": 300,
                    "name": "Planner with grid (edited elsewhere)",
                    "role": "planner",
                    "is_default": False,
                    "is_active": True,
                    "instructions": "Be concise.",
                    "prompt_blocks": {},
                    "model": None,
                    "temperature": None,
                    "max_output_tokens": None,
                    "redo_model": None,
                    "redo_temperature": None,
                    "redo_max_output_tokens": None,
                    "history_limit": 40,
                    "history_channels": "both",
                    "history_lookback_days": None,
                    "include_beds24": True,
                    "include_payments": False,
                    "include_notes": True,
                    "include_availability": False,
                    "include_tenant_brain": False,
                    "include_brain_index": True,
                    "always_include_brain_sections": [],
                    "match_inbound_language": True,
                    "escalate_keywords": [],
                    "on_no_template_match": "escalate",
                    "min_confidence": 0.5,
                    "max_redraft_attempts": 2,
                    "block_auto_send_on_fail": True,
                    "daily_token_cap": None,
                    "created_by_user_id": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    # A brand-new row (also old-shaped) - since it doesn't exist yet, the missing
                    # columns should fall back to the model default ([]), not error.
                    "id": 301,
                    "name": "New old-shaped profile",
                    "role": "checker",
                    "is_default": False,
                    "is_active": True,
                    "instructions": "Proof-read.",
                    "prompt_blocks": {},
                    "model": None,
                    "temperature": None,
                    "max_output_tokens": None,
                    "redo_model": None,
                    "redo_temperature": None,
                    "redo_max_output_tokens": None,
                    "history_limit": 40,
                    "history_channels": "both",
                    "history_lookback_days": None,
                    "include_beds24": True,
                    "include_payments": False,
                    "include_notes": True,
                    "include_availability": False,
                    "include_tenant_brain": False,
                    "include_brain_index": True,
                    "always_include_brain_sections": [],
                    "match_inbound_language": True,
                    "escalate_keywords": [],
                    "on_no_template_match": "escalate",
                    "min_confidence": 0.5,
                    "max_redraft_attempts": 2,
                    "block_auto_send_on_fail": True,
                    "daily_token_cap": None,
                    "created_by_user_id": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            ]
        },
    }

    response = _upload(client, "replace", old_shaped_export)
    assert response.status_code == 200, response.text

    db_session.expire_all()
    updated = db_session.query(AiAgentProfile).filter(AiAgentProfile.id == 300).one()
    assert updated.name == "Planner with grid (edited elsewhere)"
    # The column the old export never captured is left exactly as it was, not blanked to [].
    assert updated.instruction_sections == [{"id": "a", "label": "", "content": "Be concise.", "order": 0}]

    created = db_session.query(AiAgentProfile).filter(AiAgentProfile.id == 301).one()
    assert created.instruction_sections == []
    assert created.instruction_canvas_notes == []


def test_brain_sections_parent_child_replace_survives_fk_ordering(client, db_session):
    export_payload = {
        "schemaVersion": settings_backup_service.SCHEMA_VERSION,
        "exportedAt": "2026-01-01T00:00:00+00:00",
        "appVersion": None,
        "excludedFields": {},
        "data": {
            "brain_sections": [
                # Child listed before its parent in the file - the import must not depend on
                # array order to get FK insert ordering right.
                {
                    "id": 2,
                    "parent_id": 1,
                    "path": "policies.cancellation",
                    "slug": "cancellation",
                    "title": "Cancellation",
                    "content": "Refund rules.",
                    "color": None,
                    "position": 0,
                    "is_active": True,
                    "created_by_user_id": None,
                    "updated_by_user_id": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": 1,
                    "parent_id": None,
                    "path": "policies",
                    "slug": "policies",
                    "title": "Policies",
                    "content": None,
                    "color": None,
                    "position": 0,
                    "is_active": True,
                    "created_by_user_id": None,
                    "updated_by_user_id": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            ]
        },
    }

    response = _upload(client, "replace", export_payload)
    assert response.status_code == 200, response.text
    result = response.json()["datasets"]["brain_sections"]
    assert result["added"] == 2

    db_session.expire_all()
    child = db_session.query(BrainSection).filter(BrainSection.id == 2).one()
    assert child.parent_id == 1
    assert db_session.query(BrainSection).count() == 2
