import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.ai_reply_template import AiReplyTemplate, AiReplyTemplateBrainSection
from app.models.brain_section import BrainSection
from app.models.user import User

# Brain editing is open to any authenticated user, not just admins, so the shared `client`
# fixture (which only overrides the admin dependency) is not enough on its own.
REGULAR_USER = User(id=2, email="agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def client(client):  # noqa: F811 - deliberately wraps the conftest fixture
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _create(client, **payload):
    body = {"title": "Policies", "slug": None, "parent_id": None, "content": None, "is_active": True}
    body.update(payload)
    response = client.post("/api/brain-sections", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_derives_slug_and_path_from_title(client):
    root = _create(client, title="House Policies")
    assert root["slug"] == "house-policies"
    assert root["path"] == "house-policies"

    child = _create(client, title="Late Check-in", parent_id=root["id"], content="Arrivals after 22:00 are fine.")
    assert child["path"] == "house-policies.late-check-in"


def test_explicit_slug_is_validated(client):
    response = client.post(
        "/api/brain-sections",
        json={"title": "Bad", "slug": "Not A Slug", "parent_id": None, "content": None, "is_active": True},
    )
    assert response.status_code == 400
    assert "lowercase" in response.json()["detail"]


def test_duplicate_path_under_same_parent_is_rejected(client):
    root = _create(client, title="Property")
    _create(client, title="Wifi", parent_id=root["id"])
    response = client.post(
        "/api/brain-sections",
        json={"title": "Wifi", "slug": None, "parent_id": root["id"], "content": None, "is_active": True},
    )
    assert response.status_code == 409


def test_rename_recomputes_descendant_paths(client, db_session):
    root = _create(client, title="Policies")
    child = _create(client, title="Cancellation", parent_id=root["id"])
    grandchild = _create(client, title="Refunds", parent_id=child["id"])
    assert grandchild["path"] == "policies.cancellation.refunds"

    response = client.put(
        f"/api/brain-sections/{root['id']}",
        json={"title": "Booking Rules", "slug": "booking-rules", "content": None, "is_active": True},
    )
    assert response.status_code == 200
    assert response.json()["path"] == "booking-rules"

    paths = {
        section.id: section.path
        for section in db_session.query(BrainSection).all()
    }
    assert paths[child["id"]] == "booking-rules.cancellation"
    assert paths[grandchild["id"]] == "booking-rules.cancellation.refunds"


def test_move_recomputes_paths(client, db_session):
    first = _create(client, title="First")
    second = _create(client, title="Second")
    child = _create(client, title="Shared", parent_id=first["id"])

    response = client.post(f"/api/brain-sections/{child['id']}/move", json={"parent_id": second["id"], "position": 0})
    assert response.status_code == 200
    assert response.json()["path"] == "second.shared"
    assert db_session.query(BrainSection).filter(BrainSection.id == child["id"]).one().parent_id == second["id"]


def test_move_into_own_descendant_is_rejected(client):
    root = _create(client, title="Root")
    child = _create(client, title="Child", parent_id=root["id"])

    response = client.post(f"/api/brain-sections/{root['id']}/move", json={"parent_id": child["id"], "position": 0})
    assert response.status_code == 400
    assert "descendants" in response.json()["detail"]


def test_move_onto_itself_is_rejected(client):
    root = _create(client, title="Root")
    response = client.post(f"/api/brain-sections/{root['id']}/move", json={"parent_id": root["id"], "position": 0})
    assert response.status_code == 400


def test_delete_with_children_requires_cascade(client):
    root = _create(client, title="Root")
    _create(client, title="Child", parent_id=root["id"])

    assert client.delete(f"/api/brain-sections/{root['id']}").status_code == 409
    assert client.delete(f"/api/brain-sections/{root['id']}?cascade=true").status_code == 204


def test_delete_blocked_while_a_template_references_the_path(client, db_session):
    section = _create(client, title="Cancellation", content="Free until 7 days before.")
    template = AiReplyTemplate(
        name="Cancellation reply",
        sections=[{"label": "Body", "content": "{{brain:cancellation}}"}],
        created_by_user_id=1,
    )
    db_session.add(template)
    db_session.commit()

    response = client.delete(f"/api/brain-sections/{section['id']}")
    assert response.status_code == 409
    assert "Cancellation reply" in response.json()["detail"]


def test_delete_blocked_while_a_template_attaches_the_section(client, db_session):
    section = _create(client, title="Wifi")
    template = AiReplyTemplate(name="Attached", sections=[], created_by_user_id=1)
    template.brain_links = [AiReplyTemplateBrainSection(brain_section_id=section["id"], position=0)]
    db_session.add(template)
    db_session.commit()

    response = client.delete(f"/api/brain-sections/{section['id']}")
    assert response.status_code == 409
    assert "Attached" in response.json()["detail"]


def test_list_returns_a_nested_tree(client):
    root = _create(client, title="Root")
    _create(client, title="Child A", parent_id=root["id"])
    _create(client, title="Child B", parent_id=root["id"])

    tree = client.get("/api/brain-sections").json()
    node = next(item for item in tree if item["id"] == root["id"])
    assert [child["title"] for child in node["children"]] == ["Child A", "Child B"]

    flat = client.get("/api/brain-sections/flat").json()
    assert {item["path"] for item in flat} >= {"root", "root.child-a", "root.child-b"}
