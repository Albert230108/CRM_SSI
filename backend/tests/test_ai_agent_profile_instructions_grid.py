"""Covers the Agent Instructions grid at the API layer (app/api/ai_agent_profiles.py's
_apply_instructions): whichever mode is active on save writes both representations, an unedited
migrated profile's derived text is byte-for-byte identical to the original, prompt order (not
array order) drives the derived text, and post-it notes never leak into it."""
import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.user import User

REGULAR_USER = User(id=2, email="agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def client(client):  # noqa: F811 - wraps the conftest fixture, which only overrides the admin dep
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _base_payload(**overrides):
    body = {
        "name": "Grid test profile",
        "role": "planner",
        "is_default": False,
        "is_active": True,
        "instructions": None,
        "instruction_sections": None,
        "instruction_canvas_notes": None,
        "model": None,
        "temperature": 0.2,
        "max_output_tokens": 2048,
        "history_limit": 40,
        "history_channels": "both",
        "history_lookback_days": 30,
        "include_beds24": True,
        "include_payments": False,
        "include_notes": True,
        "include_tenant_brain": False,
        "include_brain_index": True,
        "match_inbound_language": True,
        "escalate_keywords": [],
        "on_no_template_match": "escalate",
        "min_confidence": 0.5,
        "max_redraft_attempts": 2,
        "block_auto_send_on_fail": True,
        "daily_token_cap": None,
    }
    body.update(overrides)
    return body


def test_classic_mode_mirrors_instructions_into_a_single_card(client):
    response = client.post(
        "/api/ai-agent-profiles",
        json=_base_payload(instructions="Be concise and friendly."),
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["instructions"] == "Be concise and friendly."
    assert data["instruction_sections"] == [
        {"id": None, "label": "", "content": "Be concise and friendly.", "order": 0, "x": None, "y": None, "w": None, "h": None, "z": None}
    ]
    assert data["instruction_canvas_notes"] == []


def test_classic_mode_with_empty_instructions_leaves_grid_empty(client):
    response = client.post("/api/ai-agent-profiles", json=_base_payload(instructions=None))
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["instructions"] is None
    assert data["instruction_sections"] == []


def test_grid_mode_derives_instructions_from_cards_in_order_not_array_order(client):
    sections = [
        {"id": "b", "label": "Tone", "content": "Be warm.", "order": 1},
        {"id": "a", "label": "Persona", "content": "You are the front desk.", "order": 0},
    ]
    response = client.post(
        "/api/ai-agent-profiles",
        json=_base_payload(instructions="stale text the client should not control", instruction_sections=sections),
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["instructions"] == "## Persona\nYou are the front desk.\n\n## Tone\nBe warm."
    assert [s["id"] for s in data["instruction_sections"]] == ["b", "a"]


def test_post_it_notes_are_stored_but_never_reach_derived_instructions(client):
    sections = [{"id": "a", "label": "", "content": "Only this is sent to the AI.", "order": 0}]
    notes = [{"id": "n1", "text": "Remember to review this quarterly.", "x": 10, "y": 10}]
    response = client.post(
        "/api/ai-agent-profiles",
        json=_base_payload(instruction_sections=sections, instruction_canvas_notes=notes),
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["instructions"] == "Only this is sent to the AI."
    assert data["instruction_canvas_notes"][0]["text"] == "Remember to review this quarterly."
    assert "quarterly" not in data["instructions"]


def test_unedited_migrated_profile_round_trip_is_byte_for_byte_unchanged(client):
    """Simulates the 0093 data migration's shape: one unlabeled card holding the original text
    verbatim. Saving it back through the grid (as the editor does on every open+save, even with
    no edits) must reproduce the exact same `instructions` string the 11+ raw consumers read."""
    original_text = "Line one.\n\nLine two with {{current_date}} left literal."
    create_response = client.post(
        "/api/ai-agent-profiles",
        json=_base_payload(instructions=original_text),
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["instructions"] == original_text  # classic-mode create sanity check

    # Re-save exactly what a migrated profile's grid would already hold: the single mirrored card.
    update_response = client.put(
        f"/api/ai-agent-profiles/{created['id']}",
        json=_base_payload(
            instructions="ignored because instruction_sections is provided",
            instruction_sections=created["instruction_sections"],
        ),
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["instructions"] == original_text


def test_switching_from_grid_back_to_classic_on_save_mirrors_the_submitted_text(client):
    create_response = client.post(
        "/api/ai-agent-profiles",
        json=_base_payload(
            instruction_sections=[
                {"id": "a", "label": "One", "content": "First card.", "order": 0},
                {"id": "b", "label": "Two", "content": "Second card.", "order": 1},
            ]
        ),
    )
    profile_id = create_response.json()["id"]

    update_response = client.put(
        f"/api/ai-agent-profiles/{profile_id}",
        json=_base_payload(instructions="Now edited directly in Classic mode.", instruction_sections=None),
    )
    assert update_response.status_code == 200, update_response.text
    data = update_response.json()
    assert data["instructions"] == "Now edited directly in Classic mode."
    assert data["instruction_sections"] == [
        {
            "id": None,
            "label": "",
            "content": "Now edited directly in Classic mode.",
            "order": 0,
            "x": None,
            "y": None,
            "w": None,
            "h": None,
            "z": None,
        }
    ]
