import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.ai_agent_profile import AiAgentProfile
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.user import User

REGULAR_USER = User(id=2, email="agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def client(client):  # noqa: F811 - wraps the conftest fixture, which only overrides the admin dep
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _payload(**overrides):
    body = {
        "name": "Standard planner",
        "role": "planner",
        "is_default": True,
        "is_active": True,
        "instructions": "Pick the closest template.",
        "model": None,
        "temperature": 0.2,
        "max_output_tokens": 2048,
        "history_limit": 40,
        "history_channels": "both",
        "history_lookback_days": 30,
        "include_beds24": True,
        "include_payments": False,
        "include_notes": True,
        "include_brain_index": True,
        "match_inbound_language": True,
        "escalate_keywords": ["refund", "lawyer"],
        "on_no_template_match": "escalate",
        "min_confidence": 0.6,
        "max_redraft_attempts": 2,
        "block_auto_send_on_fail": True,
        "daily_token_cap": None,
    }
    body.update(overrides)
    return body


def test_create_and_list_profiles(client):
    response = client.post("/api/ai-agent-profiles", json=_payload())
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["escalate_keywords"] == ["refund", "lawyer"]
    assert created["min_confidence"] == 0.6
    assert created["is_default"] is True

    client.post("/api/ai-agent-profiles", json=_payload(name="Strict checker", role="checker"))
    assert len(client.get("/api/ai-agent-profiles").json()) == 2
    planners = client.get("/api/ai-agent-profiles?role=planner").json()
    assert [profile["name"] for profile in planners] == ["Standard planner"]


def test_only_one_default_per_role_survives(client, db_session):
    first = client.post("/api/ai-agent-profiles", json=_payload(name="First")).json()
    second = client.post("/api/ai-agent-profiles", json=_payload(name="Second")).json()
    # A checker default must be untouched by planner defaults changing.
    checker = client.post("/api/ai-agent-profiles", json=_payload(name="Checker", role="checker")).json()

    defaults = {
        profile.id: profile.is_default
        for profile in db_session.query(AiAgentProfile).all()
    }
    assert defaults[first["id"]] is False
    assert defaults[second["id"]] is True
    assert defaults[checker["id"]] is True


def test_update_can_move_the_default(client, db_session):
    first = client.post("/api/ai-agent-profiles", json=_payload(name="First")).json()
    second = client.post("/api/ai-agent-profiles", json=_payload(name="Second", is_default=False)).json()

    response = client.put(f"/api/ai-agent-profiles/{second['id']}", json=_payload(name="Second", is_default=True))
    assert response.status_code == 200
    assert response.json()["is_default"] is True
    db_session.expire_all()
    assert db_session.query(AiAgentProfile).filter(AiAgentProfile.id == first["id"]).one().is_default is False


def test_deleting_the_default_is_refused(client):
    profile = client.post("/api/ai-agent-profiles", json=_payload()).json()
    response = client.delete(f"/api/ai-agent-profiles/{profile['id']}")
    assert response.status_code == 409
    assert "default profile" in response.json()["detail"]


def test_non_default_profile_can_be_deleted(client):
    client.post("/api/ai-agent-profiles", json=_payload(name="Keeper"))
    spare = client.post("/api/ai-agent-profiles", json=_payload(name="Spare", is_default=False)).json()
    assert client.delete(f"/api/ai-agent-profiles/{spare['id']}").status_code == 204


def test_invalid_enum_values_are_rejected(client):
    assert client.post("/api/ai-agent-profiles", json=_payload(role="wizard")).status_code == 422
    assert client.post("/api/ai-agent-profiles", json=_payload(history_channels="carrier-pigeon")).status_code == 422
    assert client.post("/api/ai-agent-profiles", json=_payload(min_confidence=1.5)).status_code == 422


def test_tenant_settings_accept_planner_mode_and_profiles(client, db_session):
    tenant = Tenant(name="Planner tenant", booking_id="B-mode-1")
    db_session.add(tenant)
    db_session.commit()
    planner = client.post("/api/ai-agent-profiles", json=_payload(name="P")).json()
    checker = client.post("/api/ai-agent-profiles", json=_payload(name="C", role="checker")).json()

    response = client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={
            "available_template_ids": [],
            "auto_draft_email": False,
            "auto_draft_whatsapp": False,
            "auto_send_email": False,
            "auto_send_whatsapp": False,
            "planner_mode": "manual",
            "planner_profile_id": planner["id"],
            "checker_profile_id": checker["id"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["planner_mode"] == "manual"
    assert body["planner_profile_id"] == planner["id"]
    assert body["checker_profile_id"] == checker["id"]


def test_profile_pinned_to_the_wrong_role_is_stored_as_unpinned(client, db_session):
    """Falling back to the role default beats persisting a pin that can never resolve."""
    tenant = Tenant(name="Mismatch tenant", booking_id="B-mode-2")
    db_session.add(tenant)
    db_session.commit()
    checker = client.post("/api/ai-agent-profiles", json=_payload(name="C", role="checker")).json()

    response = client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={
            "available_template_ids": [],
            "auto_draft_email": False,
            "auto_draft_whatsapp": False,
            "auto_send_email": False,
            "auto_send_whatsapp": False,
            "planner_mode": "auto-send",
            "planner_profile_id": checker["id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["planner_profile_id"] is None
    assert db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).one().planner_mode == "auto-send"


def test_planner_mode_defaults_to_off(client, db_session):
    tenant = Tenant(name="Fresh tenant", booking_id="B-mode-3")
    db_session.add(tenant)
    db_session.commit()

    body = client.get(f"/api/tenants/{tenant.id}/ai-settings").json()
    assert body["planner_mode"] == "off"
    assert body["planner_profile_id"] is None


def test_create_a_drafter_profile_with_prompt_block_overrides(client):
    response = client.post(
        "/api/ai-agent-profiles",
        json=_payload(name="Standard drafter", role="drafter", prompt_blocks={"sections": "Custom label"}),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "drafter"
    assert body["prompt_blocks"] == {"sections": "Custom label"}


def test_drafter_role_is_listed_and_filterable(client):
    client.post("/api/ai-agent-profiles", json=_payload(name="D", role="drafter"))
    client.post("/api/ai-agent-profiles", json=_payload(name="P", role="planner"))

    response = client.get("/api/ai-agent-profiles", params={"role": "drafter"})
    assert response.status_code == 200
    roles = {profile["role"] for profile in response.json()}
    assert roles == {"drafter"}


def test_updating_prompt_blocks_round_trips(client):
    created = client.post("/api/ai-agent-profiles", json=_payload(name="P", role="planner")).json()
    updated = client.put(
        f"/api/ai-agent-profiles/{created['id']}",
        json=_payload(name="P", role="planner", prompt_blocks={"output": ""}),
    )
    assert updated.status_code == 200
    assert updated.json()["prompt_blocks"] == {"output": ""}


def test_tenant_can_pin_a_drafter_profile(client, db_session):
    tenant = Tenant(name="Drafter pin tenant", booking_id="B-drafter-1")
    db_session.add(tenant)
    db_session.commit()
    drafter = client.post("/api/ai-agent-profiles", json=_payload(name="D", role="drafter", is_default=True)).json()

    response = client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={
            "available_template_ids": [],
            "auto_draft_email": False,
            "auto_draft_whatsapp": False,
            "auto_send_email": False,
            "auto_send_whatsapp": False,
            "planner_mode": "off",
            "drafter_profile_id": drafter["id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["drafter_profile_id"] == drafter["id"]


def test_a_checker_profile_id_is_rejected_as_a_drafter_pin(client, db_session):
    """A profile id for the wrong role must be silently unpinned, mirroring planner/checker."""
    tenant = Tenant(name="Wrong role tenant", booking_id="B-drafter-2")
    db_session.add(tenant)
    db_session.commit()
    checker = client.post("/api/ai-agent-profiles", json=_payload(name="C", role="checker")).json()

    response = client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={
            "available_template_ids": [],
            "auto_draft_email": False,
            "auto_draft_whatsapp": False,
            "auto_send_email": False,
            "auto_send_whatsapp": False,
            "planner_mode": "off",
            "drafter_profile_id": checker["id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["drafter_profile_id"] is None
