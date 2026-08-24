import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.user import User
from app.models.working_memory_rule import STATUS_ACTIVE, STATUS_PENDING_APPROVAL, WorkingMemoryRule

RULE_USER = User(id=4, email="rules@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: RULE_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_create_list_update_delete_rule(user_client, db_session):
    create_response = user_client.post(
        "/api/working-memory-rules", json={"condition_text": "Returning customer", "action_text": "Always offer a discount"}
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["status"] == STATUS_ACTIVE
    assert body["source"] == "manual"
    rule_id = body["id"]

    list_response = user_client.get("/api/working-memory-rules")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    patch_response = user_client.patch(f"/api/working-memory-rules/{rule_id}", json={"action_text": "Offer a 10% discount"})
    assert patch_response.status_code == 200
    assert patch_response.json()["action_text"] == "Offer a 10% discount"

    delete_response = user_client.delete(f"/api/working-memory-rules/{rule_id}")
    assert delete_response.status_code == 204
    assert db_session.query(WorkingMemoryRule).filter(WorkingMemoryRule.id == rule_id).first() is None


def test_create_rule_requires_both_fields(user_client):
    response = user_client.post("/api/working-memory-rules", json={"condition_text": "", "action_text": "Do something"})
    assert response.status_code == 400


def test_approve_and_reject_only_apply_to_pending_rules(user_client, db_session):
    rule = WorkingMemoryRule(condition_text="X", action_text="Y", status=STATUS_PENDING_APPROVAL, source="ai_suggested")
    db_session.add(rule)
    db_session.commit()

    approve_response = user_client.post(f"/api/working-memory-rules/{rule.id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == STATUS_ACTIVE

    # Already active - approving again is rejected as a no-op state transition.
    approve_again = user_client.post(f"/api/working-memory-rules/{rule.id}/approve")
    assert approve_again.status_code == 400
