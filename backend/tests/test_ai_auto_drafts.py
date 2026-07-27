from datetime import datetime, timezone

from app.models.ai_auto_draft import AiAutoDraft
from app.models.tenant import Tenant


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Pending Draft Tenant",
        booking_id="B-pending-draft-1",
        first_name="Sam",
        last_name="Doe",
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


def test_list_defaults_to_pending_statuses_across_tenants(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    pending = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft 1", status="pending")
    scheduled = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="draft 2", status="pending_auto_send")
    sent = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft 3", status="sent")
    db_session.add_all([pending, scheduled, sent])
    db_session.commit()

    response = non_admin_client.get("/api/ai-auto-drafts")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    # Other test modules that bypass the per-test transaction (real SessionLocal() commits, same
    # pattern as test_gmail_background_poll.py) can leave unrelated pending drafts in the shared
    # test database, so assert on presence/absence rather than exact set equality.
    assert {pending.id, scheduled.id}.issubset(ids)
    assert sent.id not in ids


def test_list_filters_by_tenant_and_channel(non_admin_client, db_session):
    tenant_a = _create_tenant(db_session, booking_id="B-pending-draft-a", name="Tenant A")
    tenant_b = _create_tenant(db_session, booking_id="B-pending-draft-b", name="Tenant B")
    draft_a = AiAutoDraft(tenant_id=tenant_a.id, channel="email", generated_text="a", status="pending")
    draft_b = AiAutoDraft(tenant_id=tenant_b.id, channel="whatsapp", generated_text="b", status="pending")
    db_session.add_all([draft_a, draft_b])
    db_session.commit()

    response = non_admin_client.get(f"/api/ai-auto-drafts?tenant_id={tenant_a.id}")
    assert [item["id"] for item in response.json()] == [draft_a.id]


def test_dismiss_and_mark_used(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/mark-used")
    assert response.status_code == 200
    assert response.json()["status"] == "used_as_manual_seed"

    draft2 = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="draft 2", status="pending")
    db_session.add(draft2)
    db_session.commit()
    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft2.id}/dismiss")
    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"

    # Neither shows up in the default pending listing anymore.
    listing = non_admin_client.get("/api/ai-auto-drafts").json()
    assert draft.id not in {item["id"] for item in listing}
    assert draft2.id not in {item["id"] for item in listing}


def test_cancel_auto_send_downgrades_to_pending(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="email",
        generated_text="draft",
        status="pending_auto_send",
        scheduled_send_at=datetime.now(timezone.utc),
    )
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/cancel-auto-send")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["scheduled_send_at"] is None

    # Still visible in the default pending listing, just no longer scheduled.
    listing = non_admin_client.get("/api/ai-auto-drafts").json()
    assert draft.id in {item["id"] for item in listing}


def test_cancel_auto_send_is_a_no_op_when_not_scheduled(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/cancel-auto-send")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
