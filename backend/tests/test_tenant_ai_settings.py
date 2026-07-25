from app.models.tenant import Tenant


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="AI Settings Tenant",
        booking_id="B-ai-settings-1",
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


def _create_template(non_admin_client, name="Template"):
    response = non_admin_client.post(
        "/api/ai-reply-templates",
        json={"name": name, "sections": [{"label": "Persona", "content": "Be helpful."}]},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_get_creates_default_settings_row(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    response = non_admin_client.get(f"/api/tenants/{tenant.id}/ai-settings")
    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": tenant.id,
        "available_template_ids": [],
        "default_email_template_id": None,
        "default_whatsapp_template_id": None,
        "auto_draft_email": False,
        "auto_draft_whatsapp": False,
        "auto_send_email": False,
        "auto_send_whatsapp": False,
    }


def test_put_updates_available_templates_and_defaults(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    template_a = _create_template(non_admin_client, "Template A")
    template_b = _create_template(non_admin_client, "Template B")

    response = non_admin_client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={
            "available_template_ids": [template_a, template_b],
            "default_email_template_id": template_a,
            "default_whatsapp_template_id": template_b,
            "auto_draft_email": False,
            "auto_draft_whatsapp": False,
            "auto_send_email": False,
            "auto_send_whatsapp": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert sorted(body["available_template_ids"]) == sorted([template_a, template_b])
    assert body["default_email_template_id"] == template_a
    assert body["default_whatsapp_template_id"] == template_b

    # Persisted, not just echoed back.
    get_response = non_admin_client.get(f"/api/tenants/{tenant.id}/ai-settings")
    assert sorted(get_response.json()["available_template_ids"]) == sorted([template_a, template_b])

    # A follow-up PUT that drops template_b from availability removes the link.
    response = non_admin_client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={
            "available_template_ids": [template_a],
            "default_email_template_id": template_a,
            "default_whatsapp_template_id": None,
        },
    )
    assert response.status_code == 200
    assert response.json()["available_template_ids"] == [template_a]
    assert response.json()["default_whatsapp_template_id"] is None


def test_auto_send_requires_auto_draft_on_the_same_channel(non_admin_client, db_session):
    tenant = _create_tenant(db_session)

    # Requesting auto-send without auto-draft is silently downgraded server-side.
    response = non_admin_client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={"auto_draft_email": False, "auto_send_email": True},
    )
    assert response.status_code == 200
    assert response.json()["auto_draft_email"] is False
    assert response.json()["auto_send_email"] is False

    # Enabling both together works.
    response = non_admin_client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={"auto_draft_email": True, "auto_send_email": True},
    )
    assert response.status_code == 200
    assert response.json()["auto_draft_email"] is True
    assert response.json()["auto_send_email"] is True

    # Turning auto-draft back off forces auto-send off too, even if the client still sends True.
    response = non_admin_client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={"auto_draft_email": False, "auto_send_email": True},
    )
    assert response.status_code == 200
    assert response.json()["auto_draft_email"] is False
    assert response.json()["auto_send_email"] is False


def test_auto_send_enforcement_is_independent_per_channel(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    response = non_admin_client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={
            "auto_draft_email": True,
            "auto_send_email": True,
            "auto_draft_whatsapp": False,
            "auto_send_whatsapp": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["auto_draft_email"] is True
    assert body["auto_send_email"] is True
    assert body["auto_draft_whatsapp"] is False
    assert body["auto_send_whatsapp"] is False
