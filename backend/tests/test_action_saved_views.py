import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.action_saved_view import ActionSavedView
from app.models.user import User

USER_A = User(id=10, email="a@example.com", password_hash="x", is_active=True, is_admin=False)
USER_B = User(id=11, email="b@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def client_as_user_a(client):
    app.dependency_overrides[get_current_user] = lambda: USER_A
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_create_list_update_delete_saved_view(client_as_user_a, db_session):
    create_response = client_as_user_a.post(
        "/api/action-saved-views",
        json={
            "name": "Overdue P1",
            "status": "open",
            "priority": "p1",
            "tag_ids": [1, 2],
            "tag_match": "all",
            "due_bucket": "overdue",
            "scope": "tenant",
            "sort_field": "priority",
            "sort_dir": "desc",
        },
    )
    assert create_response.status_code == 201
    body = create_response.json()
    view_id = body["id"]
    assert body["name"] == "Overdue P1"
    assert body["tag_ids"] == [1, 2]
    assert body["tag_match"] == "all"
    assert body["due_bucket"] == "overdue"
    assert body["scope"] == "tenant"
    assert body["sort_field"] == "priority"
    assert body["position"] == 0

    list_response = client_as_user_a.get("/api/action-saved-views")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    patch_response = client_as_user_a.patch(
        f"/api/action-saved-views/{view_id}",
        json={"name": "Renamed", "clear_priority": True, "clear_due_bucket": True},
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["name"] == "Renamed"
    assert patched["priority"] is None
    assert patched["due_bucket"] is None

    delete_response = client_as_user_a.delete(f"/api/action-saved-views/{view_id}")
    assert delete_response.status_code == 204
    assert db_session.query(ActionSavedView).filter(ActionSavedView.id == view_id).first() is None


def test_saved_views_are_private_per_user(client, db_session):
    # A single app-level dependency override means both users can't be active at once; flip it
    # between calls to model two separate users hitting the same shared endpoint.
    a_view = ActionSavedView(user_id=USER_A.id, name="A's view")
    db_session.add(a_view)
    db_session.commit()
    db_session.refresh(a_view)
    view_id = a_view.id

    app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        # User B does not see it and cannot read/patch/delete it.
        assert client.get("/api/action-saved-views").json() == []
        assert client.patch(f"/api/action-saved-views/{view_id}", json={"name": "hijack"}).status_code == 404
        assert client.delete(f"/api/action-saved-views/{view_id}").status_code == 404

        # Owner still has it intact.
        app.dependency_overrides[get_current_user] = lambda: USER_A
        owner_list = client.get("/api/action-saved-views").json()
        assert [row["name"] for row in owner_list] == ["A's view"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_create_saved_view_rejects_blank_name(client_as_user_a):
    response = client_as_user_a.post("/api/action-saved-views", json={"name": "   "})
    assert response.status_code == 400
