from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from fastapi.testclient import TestClient


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Template Tenant",
        booking_id="B-tmpl-1",
        first_name="Jane",
        last_name="Doe",
        email="jane@example.com",
        check_in="2026-08-01",
        check_out="2026-08-05",
        room_name="Studio 1",
    )
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_create_list_update_delete_template(non_admin_client):
    create_response = non_admin_client.post(
        "/api/email-templates",
        json={"name": "Welcome", "subject": "Hi {{first_name}}", "body": "Hello {{first_name}}, welcome!"},
    )
    assert create_response.status_code == 201
    template_id = create_response.json()["id"]

    list_response = non_admin_client.get("/api/email-templates")
    assert list_response.status_code == 200
    assert [t["id"] for t in list_response.json()] == [template_id]

    update_response = non_admin_client.put(
        f"/api/email-templates/{template_id}",
        json={"name": "Welcome v2", "subject": None, "body": "Updated body"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Welcome v2"
    assert update_response.json()["subject"] is None

    delete_response = non_admin_client.delete(f"/api/email-templates/{template_id}")
    assert delete_response.status_code == 204

    assert non_admin_client.get("/api/email-templates").json() == []


def test_preview_resolves_known_placeholders_and_leaves_unknown_untouched(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    create_response = non_admin_client.post(
        "/api/email-templates",
        json={
            "name": "Welcome",
            "subject": "Hi {{first_name}}",
            "body": "Hello {{first_name}} {{unknown_field}}, check-in {{check_in}}",
        },
    )
    template_id = create_response.json()["id"]

    preview_response = non_admin_client.post(
        f"/api/email-templates/{template_id}/preview",
        json={"tenant_id": tenant.id},
    )
    assert preview_response.status_code == 200
    data = preview_response.json()
    assert data["subject"] == "Hi Jane"
    assert data["body"] == "Hello Jane {{unknown_field}}, check-in 2026-08-01"


def test_template_access_is_scoped_to_owner(db_session):
    owner = User(id=301, email="owner-template@example.com", password_hash="x", is_active=True, is_admin=False)
    other = User(id=302, email="other-template@example.com", password_hash="x", is_active=True, is_admin=False)

    def override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        with TestClient(app) as owner_client:
            create_response = owner_client.post("/api/email-templates", json={"name": "Mine", "body": "hi"})
            assert create_response.status_code == 201
            template_id = create_response.json()["id"]

        app.dependency_overrides[get_current_user] = lambda: other
        with TestClient(app) as other_client:
            assert other_client.put(
                f"/api/email-templates/{template_id}", json={"name": "Hijack", "body": "x"}
            ).status_code == 403
            assert other_client.delete(f"/api/email-templates/{template_id}").status_code == 403
            assert other_client.post(
                f"/api/email-templates/{template_id}/preview", json={"tenant_id": 1}
            ).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
