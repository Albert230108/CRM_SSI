from app.models.admin_settings import AdminSettings


def test_get_admin_settings_defaults_to_null(non_admin_client):
    response = non_admin_client.get("/api/admin-settings")
    assert response.status_code == 200
    assert response.json() == {
        "forward_to_email": None,
        "ai_draft_debounce_seconds": 120,
        "ai_auto_send_delay_seconds": 300,
        "ai_auto_apply_templates_to_new_tenants": False,
        "planner_default_mode": "off",
        "brain_writer_default_enabled": False,
        "action_writer_default_enabled": False,
        "ai_daily_token_cap": None,
        "notification_whatsapp_debounce_seconds": 120,
        "notification_whatsapp_external_account_id": None,
    }


def test_put_admin_settings_sets_and_clears_notification_whatsapp_account(client, db_session):
    response = client.put("/api/admin-settings", json={"notification_whatsapp_external_account_id": "edi-crm-whatsapp"})
    assert response.status_code == 200
    assert response.json()["notification_whatsapp_external_account_id"] == "edi-crm-whatsapp"

    response = client.put("/api/admin-settings", json={"clear_notification_whatsapp_external_account_id": True})
    assert response.status_code == 200
    assert response.json()["notification_whatsapp_external_account_id"] is None


def test_put_admin_settings_updates_writer_defaults(client, db_session):
    response = client.put(
        "/api/admin-settings",
        json={"brain_writer_default_enabled": True, "action_writer_default_enabled": True},
    )
    assert response.status_code == 200
    assert response.json()["brain_writer_default_enabled"] is True
    assert response.json()["action_writer_default_enabled"] is True


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
