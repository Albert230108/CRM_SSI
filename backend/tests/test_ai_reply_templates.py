from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.user import User
from fastapi.testclient import TestClient


def test_create_list_update_delete_template(non_admin_client):
    create_response = non_admin_client.post(
        "/api/ai-reply-templates",
        json={
            "name": "Friendly check-in reminder",
            "sections": [
                {"label": "Persona", "content": "You are a friendly host."},
                {"label": "Instructions", "content": "Keep replies short and warm."},
            ],
            "include_history": True,
            "history_message_limit": 15,
            "include_beds24": True,
            "include_payments": False,
            "include_notes": True,
        },
    )
    assert create_response.status_code == 201
    body = create_response.json()
    template_id = body["id"]
    assert body["sections"] == [
        {"label": "Persona", "content": "You are a friendly host."},
        {"label": "Instructions", "content": "Keep replies short and warm."},
    ]
    assert body["include_history"] is True
    assert body["history_message_limit"] == 15
    assert body["include_notes"] is True

    list_response = non_admin_client.get("/api/ai-reply-templates")
    assert list_response.status_code == 200
    assert [t["id"] for t in list_response.json()] == [template_id]

    update_response = non_admin_client.put(
        f"/api/ai-reply-templates/{template_id}",
        json={
            "name": "Friendly check-in reminder v2",
            "sections": [{"label": "Persona", "content": "You are a concise host."}],
            "include_history": False,
            "include_beds24": False,
            "include_payments": True,
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Friendly check-in reminder v2"
    assert update_response.json()["include_payments"] is True

    delete_response = non_admin_client.delete(f"/api/ai-reply-templates/{template_id}")
    assert delete_response.status_code == 204
    assert non_admin_client.get("/api/ai-reply-templates").json() == []


def test_templates_are_shared_across_users_not_owner_scoped(db_session):
    creator = User(id=401, email="creator@example.com", password_hash="x", is_active=True, is_admin=False)
    other = User(id=402, email="other-user@example.com", password_hash="x", is_active=True, is_admin=False)

    def override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: creator
    try:
        with TestClient(app) as creator_client:
            create_response = creator_client.post(
                "/api/ai-reply-templates",
                json={"name": "Shared template", "sections": [{"label": "Persona", "content": "Be helpful."}]},
            )
            assert create_response.status_code == 201
            template_id = create_response.json()["id"]

        app.dependency_overrides[get_current_user] = lambda: other
        with TestClient(app) as other_client:
            # Any authenticated user can see, edit, and delete a shared template - no ownership gate.
            assert [t["id"] for t in other_client.get("/api/ai-reply-templates").json()] == [template_id]
            update_response = other_client.put(
                f"/api/ai-reply-templates/{template_id}",
                json={"name": "Edited by someone else", "sections": []},
            )
            assert update_response.status_code == 200
            assert update_response.json()["name"] == "Edited by someone else"
            assert other_client.delete(f"/api/ai-reply-templates/{template_id}").status_code == 204
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
