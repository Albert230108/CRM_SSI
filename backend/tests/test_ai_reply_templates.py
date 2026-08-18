from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.brain_section import BrainSection
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
    assert [{"label": s["label"], "content": s["content"]} for s in body["sections"]] == [
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


def test_update_template_keeping_existing_brain_section_does_not_500(non_admin_client, db_session):
    section_a = BrainSection(path="policies", slug="policies", title="Policies")
    section_b = BrainSection(path="pricing", slug="pricing", title="Pricing")
    db_session.add_all([section_a, section_b])
    db_session.commit()

    create_response = non_admin_client.post(
        "/api/ai-reply-templates",
        json={
            "name": "Brain-linked template",
            "sections": [{"label": "Persona", "content": "Be helpful."}],
            "brain_section_ids": [section_a.id, section_b.id],
        },
    )
    assert create_response.status_code == 201
    template_id = create_response.json()["id"]
    assert create_response.json()["brain_section_ids"] == [section_a.id, section_b.id]

    # Regression: re-submitting an update that keeps an already-linked brain section used to
    # raise psycopg2.errors.UniqueViolation on uq_ai_template_brain_section, because
    # _sync_brain_links replaced the link rows wholesale and the delete-orphan cascade flushed
    # the new INSERT before the old row's DELETE.
    update_response = non_admin_client.put(
        f"/api/ai-reply-templates/{template_id}",
        json={
            "name": "Brain-linked template",
            "sections": [{"label": "Persona", "content": "Be helpful."}],
            "brain_section_ids": [section_a.id],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["brain_section_ids"] == [section_a.id]


def test_canvas_notes_and_section_positions_round_trip(non_admin_client):
    create_response = non_admin_client.post(
        "/api/ai-reply-templates",
        json={
            "name": "Canvas template",
            "sections": [
                {"label": "Persona", "content": "Be helpful.", "id": "sec-1", "x": 10.5, "y": 20.0, "order": 0},
            ],
            "canvas_notes": [
                {"id": "note-1", "text": "Double-check with legal before using this", "x": 40.0, "y": 5.0, "color": "yellow"},
            ],
        },
    )
    assert create_response.status_code == 201
    body = create_response.json()
    template_id = body["id"]
    assert body["sections"] == [
        {
            "label": "Persona",
            "content": "Be helpful.",
            "id": "sec-1",
            "x": 10.5,
            "y": 20.0,
            "order": 0,
            "w": None,
            "h": None,
            "z": None,
        },
    ]
    assert body["canvas_notes"] == [
        {
            "id": "note-1",
            "text": "Double-check with legal before using this",
            "x": 40.0,
            "y": 5.0,
            "color": "yellow",
            "w": None,
            "h": None,
            "z": None,
        },
    ]

    get_response = non_admin_client.get(f"/api/ai-reply-templates/{template_id}")
    assert get_response.status_code == 200
    assert get_response.json()["canvas_notes"] == body["canvas_notes"]

    update_response = non_admin_client.put(
        f"/api/ai-reply-templates/{template_id}",
        json={
            "name": "Canvas template",
            "sections": [
                {"label": "Persona", "content": "Be helpful.", "id": "sec-1", "x": 99.0, "y": 20.0, "order": 0},
            ],
            "canvas_notes": [],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["sections"][0]["x"] == 99.0
    assert update_response.json()["canvas_notes"] == []


def test_canvas_sizes_and_stacking_order_round_trip(non_admin_client):
    """w/h/z are canvas-only metadata; Pydantic would silently drop them if unmodelled."""
    create_response = non_admin_client.post(
        "/api/ai-reply-templates",
        json={
            "name": "Sized canvas template",
            "sections": [
                {
                    "label": "Persona",
                    "content": "Be helpful.",
                    "id": "sec-1",
                    "x": 0.0,
                    "y": 0.0,
                    "order": 0,
                    "w": 384.0,
                    "h": 240.0,
                    "z": 7,
                },
            ],
            "canvas_notes": [
                {"id": "note-1", "text": "Behind the card", "x": 0.0, "y": 0.0, "w": 168.0, "h": 144.0, "z": 3},
            ],
        },
    )
    assert create_response.status_code == 201
    template_id = create_response.json()["id"]

    get_response = non_admin_client.get(f"/api/ai-reply-templates/{template_id}")
    assert get_response.status_code == 200
    body = get_response.json()
    assert (body["sections"][0]["w"], body["sections"][0]["h"], body["sections"][0]["z"]) == (384.0, 240.0, 7)
    assert (body["canvas_notes"][0]["w"], body["canvas_notes"][0]["h"], body["canvas_notes"][0]["z"]) == (168.0, 144.0, 3)

    update_response = non_admin_client.put(
        f"/api/ai-reply-templates/{template_id}",
        json={
            "name": "Sized canvas template",
            "sections": [
                {
                    "label": "Persona",
                    "content": "Be helpful.",
                    "id": "sec-1",
                    "x": 0.0,
                    "y": 0.0,
                    "order": 0,
                    "w": 288.0,
                    "h": 192.0,
                    "z": 9,
                },
            ],
            "canvas_notes": [],
        },
    )
    assert update_response.status_code == 200
    updated_section = update_response.json()["sections"][0]
    assert (updated_section["w"], updated_section["h"], updated_section["z"]) == (288.0, 192.0, 9)


def test_empty_sections_and_notes_are_persisted_not_dropped(non_admin_client):
    """The canvas keeps blank placeholders the user positioned; the prompt builder skips them."""
    create_response = non_admin_client.post(
        "/api/ai-reply-templates",
        json={
            "name": "Template with placeholders",
            "sections": [
                {"label": "Persona", "content": "Be helpful.", "id": "sec-1", "x": 0.0, "y": 0.0, "order": 0},
                {"label": "", "content": "", "id": "sec-blank", "x": 312.0, "y": 0.0, "order": 1},
            ],
            "canvas_notes": [{"id": "note-blank", "text": "", "x": 0.0, "y": -168.0}],
        },
    )
    assert create_response.status_code == 201
    template_id = create_response.json()["id"]

    body = non_admin_client.get(f"/api/ai-reply-templates/{template_id}").json()
    assert [section["id"] for section in body["sections"]] == ["sec-1", "sec-blank"]
    assert [note["id"] for note in body["canvas_notes"]] == ["note-blank"]


def test_get_ai_reply_template_by_id_returns_404_when_missing(non_admin_client):
    response = non_admin_client.get("/api/ai-reply-templates/999999")
    assert response.status_code == 404


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
