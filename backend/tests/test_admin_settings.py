from app.models.admin_settings import AdminSettings


def test_get_admin_settings_defaults_to_null(non_admin_client):
    response = non_admin_client.get("/api/admin-settings")
    assert response.status_code == 200
    assert response.json() == {
        "forward_to_email": None,
        "ai_draft_debounce_seconds": 120,
        "ai_auto_send_delay_seconds": 300,
    }


def test_put_admin_settings_requires_admin(non_admin_client):
    response = non_admin_client.put("/api/admin-settings", json={"forward_to_email": "ai@example.com"})
    assert response.status_code == 403


def test_put_admin_settings_upserts_singleton_row(client, db_session):
    response = client.put("/api/admin-settings", json={"forward_to_email": "ai@example.com"})
    assert response.status_code == 200
    assert response.json()["forward_to_email"] == "ai@example.com"

    rows = db_session.query(AdminSettings).all()
    assert len(rows) == 1
    assert rows[0].forward_to_email == "ai@example.com"

    response = client.put("/api/admin-settings", json={"forward_to_email": "other@example.com"})
    assert response.status_code == 200

    rows = db_session.query(AdminSettings).all()
    assert len(rows) == 1
    assert rows[0].forward_to_email == "other@example.com"


def test_put_admin_settings_clears_address_with_null(client, db_session):
    client.put("/api/admin-settings", json={"forward_to_email": "ai@example.com"})
    response = client.put("/api/admin-settings", json={"forward_to_email": None})
    assert response.status_code == 200
    assert response.json()["forward_to_email"] is None
