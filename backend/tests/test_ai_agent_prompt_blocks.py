"""Covers ai_prompt_blocks.resolve_blocks and the /ai-agent-profiles/prompt-blocks registry."""
import pytest
from datetime import datetime, timedelta, timezone

from app.core.dependencies import get_current_user
from app.main import app
from app.models.ai_agent_profile import AiAgentProfile
from app.models.user import User
from app.services import ai_prompt_blocks, datetime_placeholders

REGULAR_USER = User(id=2, email="agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_resolve_blocks_falls_back_to_defaults_when_profile_has_no_overrides():
    profile = AiAgentProfile(name="P", role="planner", prompt_blocks={})
    resolved = ai_prompt_blocks.resolve_blocks(profile, "planner")
    assert resolved == ai_prompt_blocks.DEFAULTS_BY_ROLE["planner"]


def test_resolve_blocks_falls_back_to_defaults_when_profile_is_none():
    resolved = ai_prompt_blocks.resolve_blocks(None, "checker")
    assert resolved == ai_prompt_blocks.DEFAULTS_BY_ROLE["checker"]


def test_resolve_blocks_override_replaces_a_single_key():
    profile = AiAgentProfile(name="P", role="planner", prompt_blocks={"preamble": "Custom preamble."})
    resolved = ai_prompt_blocks.resolve_blocks(profile, "planner")
    assert resolved["preamble"] == "Custom preamble."
    # Every other key is untouched.
    for key, default in ai_prompt_blocks.DEFAULTS_BY_ROLE["planner"].items():
        if key != "preamble":
            assert resolved[key] == default


def test_resolve_blocks_empty_string_override_removes_the_block():
    """A key present with an empty value must win over the default - that is how a block is deleted."""
    profile = AiAgentProfile(name="P", role="checker", prompt_blocks={"output": ""})
    resolved = ai_prompt_blocks.resolve_blocks(profile, "checker")
    assert resolved["output"] == ""


def test_resolve_blocks_ignores_keys_the_role_does_not_define():
    profile = AiAgentProfile(name="P", role="drafter", prompt_blocks={"not_a_real_key": "junk"})
    resolved = ai_prompt_blocks.resolve_blocks(profile, "drafter")
    assert "not_a_real_key" not in resolved
    assert resolved == ai_prompt_blocks.DEFAULTS_BY_ROLE["drafter"]


def test_fill_substitutes_named_placeholders():
    text = ai_prompt_blocks.fill("## History (last {limit} across {scope})", limit=5, scope="email")
    assert text == "## History (last 5 across email)"


def test_fill_tolerates_a_stray_brace_in_operator_text():
    """str.replace, not str.format, so an unmatched brace in operator-written text cannot raise."""
    text = ai_prompt_blocks.fill("Note: {unmatched", limit=5)
    assert text == "Note: {unmatched"


def test_resolve_datetime_placeholders_expands_known_tokens(monkeypatch):
    fixed_now = datetime(2026, 8, 27, 9, 8, 7, tzinfo=timezone(timedelta(hours=2)))
    monkeypatch.setattr(datetime_placeholders, '_now', lambda: fixed_now)

    text = datetime_placeholders.resolve_datetime_placeholders(
        'Before {{current_date}} / {{current_time}} / {{current_datetime}} / {{brain:keep}} after'
    )

    assert text == (
        f"Before {fixed_now.date().isoformat()} / {fixed_now.time().isoformat(timespec='seconds')} / "
        f"{fixed_now.isoformat(timespec='seconds')} / " + "{{brain:keep}} after"
    )


def test_resolve_blocks_resolves_datetime_placeholders_in_overrides(monkeypatch):
    fixed_now = datetime(2026, 8, 27, 9, 8, 7, tzinfo=timezone(timedelta(hours=2)))
    monkeypatch.setattr(datetime_placeholders, '_now', lambda: fixed_now)

    profile = AiAgentProfile(name='P', role='planner', prompt_blocks={'preamble': 'Start {{current_datetime}}'})
    resolved = ai_prompt_blocks.resolve_blocks(profile, 'planner')

    assert resolved['preamble'] == f"Start {fixed_now.isoformat(timespec='seconds')}"


def test_join_omits_the_missing_side():
    assert ai_prompt_blocks.join("## Heading", "") == "## Heading"
    assert ai_prompt_blocks.join("", "body text") == "body text"
    assert ai_prompt_blocks.join("## Heading", "body") == "## Heading\nbody"
    assert ai_prompt_blocks.join("", "") == ""


@pytest.mark.parametrize("role", ["planner", "checker", "drafter", "memory_redo", "memory_qa"])
def test_prompt_blocks_endpoint_returns_the_registry_for_each_role(user_client, role):
    response = user_client.get("/api/ai-agent-profiles/prompt-blocks", params={"role": role})
    assert response.status_code == 200
    body = response.json()
    keys = {entry["key"] for entry in body}
    assert keys == set(ai_prompt_blocks.DEFAULTS_BY_ROLE[role])
    for entry in body:
        assert entry["default"] == ai_prompt_blocks.DEFAULTS_BY_ROLE[role][entry["key"]]
        assert entry["group"] in ("structure", "context")


def test_prompt_blocks_endpoint_rejects_an_unknown_role(user_client):
    response = user_client.get("/api/ai-agent-profiles/prompt-blocks", params={"role": "wizard"})
    assert response.status_code == 422
