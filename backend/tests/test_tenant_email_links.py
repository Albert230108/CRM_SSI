import time
from unittest.mock import AsyncMock, patch

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from app.services.background_jobs import get_job

REGULAR_USER = User(id=2, email="agent@example.com", password_hash="x", is_active=True, is_admin=False)

NO_OP_GMAIL_SYNC_RESULT = {"accounts_checked": 0, "accounts_failed": 0, "conversations_matched": 0}


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def wait_for_job(job_id, timeout=2.0):
    deadline = time.monotonic() + timeout
    job = get_job(job_id)
    while job and job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        job = get_job(job_id)
    return job


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def mock_gmail_sync():
    with patch("app.api.tenant_email_links.sync_email_across_gmail_accounts", return_value=NO_OP_GMAIL_SYNC_RESULT) as mocked:
        yield mocked


def test_create_email_link_happy_path(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-email-1")
    fake_info_item = {"id": "999", "code": "CRM_EMAIL", "text": "guest@example.com"}

    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value=fake_info_item)) as mocked_add:
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert response.status_code == 200
    body = response.json()
    link = body["link"]
    assert link["email"] == "guest@example.com"
    assert link["tenant_id"] == tenant.id
    assert link["is_active"] is True
    assert link["beds24_sync_status"] == "synced"
    assert link["linked_by_user_id"] == REGULAR_USER.id
    assert body["gmail_sync_job_id"]
    mocked_add.assert_awaited_once_with("B-email-1", "CRM_EMAIL", "guest@example.com")


def test_create_email_link_triggers_gmail_sync_job(user_client, db_session, mock_gmail_sync):
    tenant = create_tenant(db_session, booking_id="B-email-gmail-sync")
    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "1"})):
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert response.status_code == 200
    job_id = response.json()["gmail_sync_job_id"]
    assert job_id

    job = wait_for_job(job_id)
    assert job is not None
    assert job["status"] == "done"
    assert job["result"] == NO_OP_GMAIL_SYNC_RESULT
    mock_gmail_sync.assert_called_once_with("guest@example.com")


def test_create_email_link_beds24_failure_keeps_crm_link(user_client, db_session):
    from fastapi import HTTPException

    tenant = create_tenant(db_session, booking_id="B-email-fail")
    with patch(
        "app.api.tenant_email_links.add_booking_info_item",
        new=AsyncMock(side_effect=HTTPException(status_code=502, detail="Beds24 upstream error")),
    ):
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert response.status_code == 200
    link = response.json()["link"]
    assert link["beds24_sync_status"] == "failed"
    assert link["is_active"] is True

    links = user_client.get(f"/api/tenants/{tenant.id}/email-links").json()
    assert len(links) == 1
    assert links[0]["beds24_sync_status"] == "failed"


def test_create_email_link_conflict_requires_confirmation(user_client, db_session):
    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="B-conflict-a")
    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="B-conflict-b")

    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "1"})):
        first = user_client.post(f"/api/tenants/{tenant_a.id}/email-links", json={"email": "shared@example.com"})
    assert first.status_code == 200

    without_confirm = user_client.post(f"/api/tenants/{tenant_b.id}/email-links", json={"email": "shared@example.com"})
    assert without_confirm.status_code == 409
    detail = without_confirm.json()["detail"]
    assert detail["conflicting_tenant_id"] == tenant_a.id
    assert detail["conflicting_tenant_name"] == "Tenant A"

    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "2"})):
        with_confirm = user_client.post(
            f"/api/tenants/{tenant_b.id}/email-links",
            json={"email": "shared@example.com", "confirm_conflict": True},
        )
    assert with_confirm.status_code == 200
    assert with_confirm.json()["link"]["tenant_id"] == tenant_b.id

    a_links = user_client.get(f"/api/tenants/{tenant_a.id}/email-links").json()
    b_links = user_client.get(f"/api/tenants/{tenant_b.id}/email-links").json()
    assert len(a_links) == 1
    assert len(b_links) == 1


def test_unlink_email_link_removes_beds24_info_item(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-unlink-email")
    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "555"})):
        created = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"}).json()["link"]

    with patch("app.api.tenant_email_links.delete_booking_info_item", new=AsyncMock(return_value=None)) as mocked_delete:
        delete_response = user_client.delete(f"/api/tenants/{tenant.id}/email-links/{created['id']}")

    assert delete_response.status_code == 200
    body = delete_response.json()
    assert body["link"]["is_active"] is False
    assert body["deleted_conversations"] == 0
    assert body["shared_conversations_unlinked"] == 0
    mocked_delete.assert_awaited_once_with("B-unlink-email", "555")

    active_links = user_client.get(f"/api/tenants/{tenant.id}/email-links").json()
    assert active_links == []


def _make_conversation_matched_to_email(db_session, tenant_id, email, provider_thread_id):
    from datetime import datetime, timezone

    from app.models.gmail_integration import Conversation, ConversationMessage
    from app.models.tenant_conversation_link import TenantConversationLink

    conversation = Conversation(provider="gmail", provider_thread_id=provider_thread_id, tenant_id=tenant_id, subject="Re: Booking")
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id=f"msg-{provider_thread_id}",
            direction="inbound",
            sender_email=email,
            recipient_email="info@shortstayinn.com",
            subject="Re: Booking",
            body="Hi",
            sent_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(TenantConversationLink(tenant_id=tenant_id, conversation_id=conversation.id, matched_email=email))
    db_session.commit()
    return conversation.id


def test_unlink_email_deletes_matched_conversations(user_client, db_session):
    from app.models.gmail_integration import Conversation, ConversationMessage

    tenant = create_tenant(db_session, booking_id="B-unlink-conv")
    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "1"})):
        created = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"}).json()["link"]

    conversation_id = _make_conversation_matched_to_email(db_session, tenant.id, "guest@example.com", "thread-unlink-1")

    with patch("app.api.tenant_email_links.delete_booking_info_item", new=AsyncMock(return_value=None)):
        delete_response = user_client.delete(f"/api/tenants/{tenant.id}/email-links/{created['id']}")

    assert delete_response.status_code == 200
    body = delete_response.json()
    assert body["deleted_conversations"] == 1
    assert body["shared_conversations_unlinked"] == 0

    assert db_session.query(Conversation).filter(Conversation.id == conversation_id).first() is None
    assert db_session.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).count() == 0


def test_unlink_email_keeps_conversation_shared_with_another_tenant(user_client, db_session):
    from app.models.gmail_integration import Conversation, ConversationMessage
    from app.models.tenant_conversation_link import TenantConversationLink

    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="B-unlink-shared-a")
    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="B-unlink-shared-b")

    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "1"})):
        created = user_client.post(f"/api/tenants/{tenant_a.id}/email-links", json={"email": "shared@example.com"}).json()["link"]

    conversation_id = _make_conversation_matched_to_email(db_session, tenant_a.id, "shared@example.com", "thread-shared-1")
    db_session.add(TenantConversationLink(tenant_id=tenant_b.id, conversation_id=conversation_id, matched_email="shared@example.com"))
    db_session.commit()

    with patch("app.api.tenant_email_links.delete_booking_info_item", new=AsyncMock(return_value=None)):
        delete_response = user_client.delete(f"/api/tenants/{tenant_a.id}/email-links/{created['id']}")

    assert delete_response.status_code == 200
    body = delete_response.json()
    assert body["deleted_conversations"] == 0
    assert body["shared_conversations_unlinked"] == 1

    # Conversation/messages survive since tenant B is still actively linked to it.
    assert db_session.query(Conversation).filter(Conversation.id == conversation_id).first() is not None
    assert db_session.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).count() == 1

    tenant_a_link = (
        db_session.query(TenantConversationLink)
        .filter(TenantConversationLink.tenant_id == tenant_a.id, TenantConversationLink.conversation_id == conversation_id)
        .first()
    )
    tenant_b_link = (
        db_session.query(TenantConversationLink)
        .filter(TenantConversationLink.tenant_id == tenant_b.id, TenantConversationLink.conversation_id == conversation_id)
        .first()
    )
    assert tenant_a_link.unlinked_at is not None
    assert tenant_b_link.unlinked_at is None


def test_relink_same_email_same_tenant_is_idempotent(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-idempotent")
    with patch("app.api.tenant_email_links.add_booking_info_item", new=AsyncMock(return_value={"id": "1"})) as mocked_add:
        first = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})
        second = user_client.post(f"/api/tenants/{tenant.id}/email-links", json={"email": "guest@example.com"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["link"]["id"] == second.json()["link"]["id"]
    assert second.json()["gmail_sync_job_id"] is None
    mocked_add.assert_awaited_once()

    links = user_client.get(f"/api/tenants/{tenant.id}/email-links").json()
    assert len(links) == 1


def test_get_auto_add_threads_defaults_true(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-auto-add-default")
    response = user_client.get(f"/api/tenants/{tenant.id}/auto-add-threads")
    assert response.status_code == 200
    assert response.json() == {"tenant_id": tenant.id, "auto_add": True}


def test_auto_add_threads_toggle_persists(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-auto-add-toggle")

    response = user_client.patch(f"/api/tenants/{tenant.id}/auto-add-threads", json={"auto_add": False})
    assert response.status_code == 200
    assert response.json() == {"tenant_id": tenant.id, "auto_add": False}

    db_session.refresh(tenant)
    assert tenant.auto_add_shared_email_threads is False


def test_shared_threads_lists_visibility_and_shared_flag(user_client, db_session):
    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="B-shared-threads-a")
    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="B-shared-threads-b")

    conversation_id = _make_conversation_matched_to_email(db_session, tenant_a.id, "shared@example.com", "thread-list-1")
    from app.models.tenant_conversation_link import TenantConversationLink

    db_session.add(TenantConversationLink(tenant_id=tenant_b.id, conversation_id=conversation_id, matched_email="shared@example.com"))
    db_session.commit()

    response = user_client.get(f"/api/tenants/{tenant_a.id}/shared-threads")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["conversation_id"] == conversation_id
    assert body[0]["is_visible"] is True
    assert body[0]["shared_with_other_tenants"] is True


def test_update_conversation_visibility_hides_and_reveals_thread(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-visibility-toggle")
    conversation_id = _make_conversation_matched_to_email(db_session, tenant.id, "guest@example.com", "thread-visibility-1")

    hide_response = user_client.patch(
        f"/api/tenants/{tenant.id}/conversations/{conversation_id}/visibility", json={"is_visible": False}
    )
    assert hide_response.status_code == 200
    assert hide_response.json()["is_visible"] is False
    assert hide_response.json()["shared_with_other_tenants"] is False

    show_response = user_client.patch(
        f"/api/tenants/{tenant.id}/conversations/{conversation_id}/visibility", json={"is_visible": True}
    )
    assert show_response.status_code == 200
    assert show_response.json()["is_visible"] is True


def test_update_conversation_visibility_404_for_unlinked_conversation(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-visibility-404")
    response = user_client.patch(f"/api/tenants/{tenant.id}/conversations/999999/visibility", json={"is_visible": False})
    assert response.status_code == 404


def test_permissions_require_authentication(client_without_webhook_secret, db_session):
    from app.core.dependencies import get_current_user as real_get_current_user

    app.dependency_overrides.pop(real_get_current_user, None)
    tenant = create_tenant(db_session, booking_id="B-perm-email")
    response = client_without_webhook_secret.post(
        f"/api/tenants/{tenant.id}/email-links",
        json={"email": "guest@example.com"},
    )
    assert response.status_code == 401


def test_shared_threads_includes_unshared_threads_with_a_preview(user_client, db_session):
    """Every linked thread gets a visibility toggle, not just genuinely shared ones.

    The Manage emails UI used to filter its list down to shared_with_other_tenants, so a
    tenant whose threads were all its own had no way to hide a noisy one at all.
    """
    tenant = create_tenant(db_session, name="Solo Tenant", booking_id="B-unshared-threads")
    conversation_id = _make_conversation_matched_to_email(
        db_session, tenant.id, "solo@example.com", "thread-unshared-1"
    )

    response = user_client.get(f"/api/tenants/{tenant.id}/shared-threads")
    assert response.status_code == 200
    body = response.json()

    assert len(body) == 1
    thread = body[0]
    assert thread["conversation_id"] == conversation_id
    assert thread["shared_with_other_tenants"] is False
    # Preview of the last message, so a collapsed thread row is still identifiable.
    assert thread["preview_text"] == "Hi"
    assert thread["last_message_direction"] == "inbound"


def test_sync_link_to_beds24_pushes_a_backfilled_link(user_client, db_session):
    """Backfilled links exist in the CRM without a matching info item on the booking."""
    from app.models.tenant_email_address import TenantEmailAddress

    tenant = create_tenant(db_session, name="Backfilled Tenant", booking_id="B-push-beds24")
    link = TenantEmailAddress(
        tenant_id=tenant.id,
        email="backfilled@example.com",
        source="beds24_backfill",
        beds24_sync_status="not_synced",
        is_active=True,
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    with patch(
        "app.api.tenant_email_links.add_booking_info_item",
        new=AsyncMock(return_value={"id": 4321}),
    ) as mocked:
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links/{link.id}/sync-beds24")

    assert response.status_code == 200
    assert response.json()["beds24_sync_status"] == "synced"
    mocked.assert_awaited_once()
    db_session.refresh(link)
    assert link.beds24_info_item_id == "4321"


def test_sync_link_to_beds24_records_failure_without_unlinking(user_client, db_session):
    from fastapi import HTTPException

    from app.models.tenant_email_address import TenantEmailAddress

    tenant = create_tenant(db_session, name="Failing Push Tenant", booking_id="B-push-fails")
    link = TenantEmailAddress(
        tenant_id=tenant.id, email="failing@example.com", beds24_sync_status="not_synced", is_active=True
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    with patch(
        "app.api.tenant_email_links.add_booking_info_item",
        new=AsyncMock(side_effect=HTTPException(status_code=502, detail="Beds24 unreachable")),
    ):
        response = user_client.post(f"/api/tenants/{tenant.id}/email-links/{link.id}/sync-beds24")

    assert response.status_code == 200
    assert response.json()["beds24_sync_status"] == "failed"
    db_session.refresh(link)
    # The CRM-side link still drives Gmail matching, so it must survive a Beds24 outage.
    assert link.is_active is True
