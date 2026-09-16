import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.app_knowledge_entry import AppKnowledgeEntry
from app.models.user import User
from app.services import ai_assistant_service, gemini_client

ASSISTANT_USER = User(id=11, email="assistant-user@example.com", password_hash="x", is_active=True, is_admin=False)
OTHER_USER = User(id=12, email="other-user@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: ASSISTANT_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _mock_answer(monkeypatch, text="Here's the answer."):
    def fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(text=text, parsed={"action": "answer", "answer": text}, model="fake", prompt_tokens=1, output_tokens=1, latency_ms=1)

    monkeypatch.setattr(ai_assistant_service.gemini_client, "generate", fake_generate)


def test_conversation_lifecycle(user_client):
    create_response = user_client.post("/api/ai-assistant/conversations", json={"title": "My chat"})
    assert create_response.status_code == 201
    conversation_id = create_response.json()["id"]
    assert create_response.json()["title"] == "My chat"

    list_response = user_client.get("/api/ai-assistant/conversations")
    assert list_response.status_code == 200
    assert any(c["id"] == conversation_id for c in list_response.json())

    messages_response = user_client.get(f"/api/ai-assistant/conversations/{conversation_id}")
    assert messages_response.status_code == 200
    assert messages_response.json() == []

    rename_response = user_client.patch(f"/api/ai-assistant/conversations/{conversation_id}", json={"title": "Renamed"})
    assert rename_response.status_code == 200
    assert rename_response.json()["title"] == "Renamed"

    delete_response = user_client.delete(f"/api/ai-assistant/conversations/{conversation_id}")
    assert delete_response.status_code == 204

    missing_response = user_client.get(f"/api/ai-assistant/conversations/{conversation_id}")
    assert missing_response.status_code == 404


def test_conversation_is_scoped_to_its_owner(user_client):
    create_response = user_client.post("/api/ai-assistant/conversations", json={})
    conversation_id = create_response.json()["id"]

    # Switch the auth override mid-test rather than using a second client fixture: both fixtures
    # would share the same TestClient/app.dependency_overrides, so a second fixture's setup would
    # just clobber the first's override before the test body ever runs.
    app.dependency_overrides[get_current_user] = lambda: OTHER_USER
    try:
        other_response = user_client.get(f"/api/ai-assistant/conversations/{conversation_id}")
        assert other_response.status_code == 404

        other_list = user_client.get("/api/ai-assistant/conversations")
        assert all(c["id"] != conversation_id for c in other_list.json())
    finally:
        app.dependency_overrides[get_current_user] = lambda: ASSISTANT_USER


def test_ask_endpoint_rejects_blank_question(user_client):
    create_response = user_client.post("/api/ai-assistant/conversations", json={})
    conversation_id = create_response.json()["id"]

    response = user_client.post(f"/api/ai-assistant/conversations/{conversation_id}/messages", json={"question": "   "})
    assert response.status_code == 400


def test_ask_endpoint_persists_and_returns_assistant_message(user_client, monkeypatch):
    _mock_answer(monkeypatch, "Try the settings page.")
    create_response = user_client.post("/api/ai-assistant/conversations", json={})
    conversation_id = create_response.json()["id"]

    ask_response = user_client.post(
        f"/api/ai-assistant/conversations/{conversation_id}/messages",
        json={"question": "Where are settings?", "screen_context": {"pathname": "/dashboard"}, "use_crm": False},
    )
    assert ask_response.status_code == 201
    assert ask_response.json()["role"] == "assistant"
    assert ask_response.json()["content"] == "Try the settings page."

    history_response = user_client.get(f"/api/ai-assistant/conversations/{conversation_id}")
    roles = [m["role"] for m in history_response.json()]
    assert roles == ["user", "assistant"]


def test_ask_endpoint_requires_auth(client):
    response = client.post("/api/ai-assistant/conversations", json={})
    assert response.status_code == 401


def test_knowledge_crud(user_client, db_session):
    create_response = user_client.post(
        "/api/ai-assistant/knowledge",
        json={"title": "WhatsApp linking", "body": "Link a chat manually from the tenant page.", "category": "whatsapp"},
    )
    assert create_response.status_code == 201
    entry_id = create_response.json()["id"]
    assert create_response.json()["source"] == "user"

    list_response = user_client.get("/api/ai-assistant/knowledge")
    assert any(e["id"] == entry_id for e in list_response.json())

    update_response = user_client.patch(f"/api/ai-assistant/knowledge/{entry_id}", json={"body": "Updated body."})
    assert update_response.status_code == 200
    assert update_response.json()["body"] == "Updated body."

    delete_response = user_client.delete(f"/api/ai-assistant/knowledge/{entry_id}")
    assert delete_response.status_code == 204
    assert db_session.query(AppKnowledgeEntry).filter(AppKnowledgeEntry.id == entry_id).first() is None


def test_knowledge_create_rejects_blank_fields(user_client):
    response = user_client.post("/api/ai-assistant/knowledge", json={"title": "  ", "body": "  "})
    assert response.status_code == 400
