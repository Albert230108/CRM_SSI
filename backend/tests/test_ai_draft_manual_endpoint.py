from app.models.tenant import Tenant
from app.services import ai_reply_service
from app.services.gemini_client import GeminiClientError


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Manual Draft Tenant",
        booking_id="B-manual-draft-1",
        first_name="Sam",
        last_name="Doe",
        email="sam@example.com",
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


def _mock_generate_text(monkeypatch, text="Generated reply"):
    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", lambda prompt: text)


def test_generate_with_explicit_template_id(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template_id = _create_template(non_admin_client)
    _mock_generate_text(monkeypatch, "Hello from Gemini")

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-draft",
        json={"channel": "email", "template_id": template_id, "rough_draft": "let them know check-in is 3pm"},
    )
    assert response.status_code == 200
    assert response.json() == {"generated_text": "Hello from Gemini", "formatted_text": None, "template_id": template_id}


def test_generate_falls_back_to_tenant_default_template(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template_id = _create_template(non_admin_client, "Default WhatsApp template")
    non_admin_client.put(
        f"/api/tenants/{tenant.id}/ai-settings",
        json={"available_template_ids": [template_id], "default_whatsapp_template_id": template_id},
    )
    _mock_generate_text(monkeypatch, "Default template reply")

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-draft",
        json={"channel": "whatsapp", "rough_draft": None},
    )
    assert response.status_code == 200
    assert response.json()["template_id"] == template_id
    assert response.json()["generated_text"] == "Default template reply"
    assert response.json()["formatted_text"] is None


def test_generate_without_template_or_default_returns_400(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-draft",
        json={"channel": "email"},
    )
    assert response.status_code == 400


def test_generate_rejects_unsupported_channel(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-draft",
        json={"channel": "sms"},
    )
    assert response.status_code == 400


def test_generate_with_missing_template_returns_404(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-draft",
        json={"channel": "email", "template_id": 999999},
    )
    assert response.status_code == 404


def test_gemini_failure_returns_502(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template_id = _create_template(non_admin_client)

    def failing_generate_text(prompt: str) -> str:
        raise GeminiClientError("boom")

    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", failing_generate_text)

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-draft",
        json={"channel": "email", "template_id": template_id, "rough_draft": "hi"},
    )
    assert response.status_code == 502


def test_preview_returns_exact_payload_without_calling_gemini(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template_id = _create_template(non_admin_client)

    def unexpected_call(prompt: str) -> str:
        raise AssertionError("preview must not call Gemini")

    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", unexpected_call)

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/ai-draft/preview",
        json={"channel": "email", "template_id": template_id, "rough_draft": "let them know check-in is 3pm"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["template_id"] == template_id
    assert "Be helpful." in data["payload"]
    assert "let them know check-in is 3pm" in data["payload"]
    assert data["char_count"] == len(data["payload"])
    assert data["approx_token_count"] == len(data["payload"]) // 4


def test_preview_payload_matches_generated_call_exactly(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template_id = _create_template(non_admin_client)
    captured = {}

    def capturing_generate(prompt: str) -> str:
        captured["prompt"] = prompt
        return "Generated reply"

    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", capturing_generate)

    body = {"channel": "email", "template_id": template_id, "rough_draft": "hi there"}
    preview_response = non_admin_client.post(f"/api/communications/tenants/{tenant.id}/ai-draft/preview", json=body)
    generate_response = non_admin_client.post(f"/api/communications/tenants/{tenant.id}/ai-draft", json=body)

    assert preview_response.json()["payload"] == captured["prompt"]
    assert generate_response.status_code == 200
