"""Hidden shared email threads must behave as if they were never linked to the tenant.

Covers two behaviours added on top of the read-time visibility filtering that already existed:
1. Hiding a thread cleans up the pending auto-draft artifacts that were created for the tenant
   while the thread was still visible (draft dismissed, debounce trigger removed).
2. The AI-drafts read model re-resolves "Open thread" to whichever tenant currently has the
   shared thread visible, so a stale draft never routes to a hidden tenant.
"""

from datetime import datetime, timezone

from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.gmail_integration import Conversation, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink


def _make_conversation(db, account_id: int, thread_id: str) -> Conversation:
    conversation = Conversation(provider="gmail", provider_account_id=account_id, provider_thread_id=thread_id)
    db.add(conversation)
    db.flush()
    return conversation


def _link(db, tenant_id: int, conversation_id: int, *, is_visible: bool) -> None:
    db.add(
        TenantConversationLink(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            matched_email="shared@example.com",
            is_visible=is_visible,
        )
    )


def test_hiding_thread_dismisses_that_tenants_pending_draft_and_trigger(non_admin_client, db_session):
    account = GmailAccount(email_address="hide-cleanup-account@example.com", is_active=True)
    tenant_a = Tenant(name="Tenant A", booking_id="booking-hide-cleanup-a")
    tenant_b = Tenant(name="Tenant B", booking_id="booking-hide-cleanup-b")
    db_session.add_all([account, tenant_a, tenant_b])
    db_session.flush()

    conversation = _make_conversation(db_session, account.id, "thread-hide-cleanup")
    _link(db_session, tenant_a.id, conversation.id, is_visible=True)
    _link(db_session, tenant_b.id, conversation.id, is_visible=True)

    draft_a = AiAutoDraft(
        tenant_id=tenant_a.id, channel="email", email_thread_id=conversation.id,
        generated_text="draft for A", status="pending",
    )
    draft_b = AiAutoDraft(
        tenant_id=tenant_b.id, channel="email", email_thread_id=conversation.id,
        generated_text="draft for B", status="pending",
    )
    trigger_a = AiAutoDraftTrigger(
        tenant_id=tenant_a.id, channel="email",
        trigger_at=datetime.now(timezone.utc),
        email_thread_id=conversation.id,
    )
    db_session.add_all([draft_a, draft_b, trigger_a])
    db_session.commit()

    response = non_admin_client.patch(
        f"/api/tenants/{tenant_a.id}/conversations/{conversation.id}/visibility",
        json={"is_visible": False},
    )
    assert response.status_code == 200

    db_session.expire_all()
    # Tenant A's in-flight draft is dismissed and its trigger removed - the thread is now hidden
    # for A, so nothing about it may keep surfacing on the Pending AI Drafts page.
    assert db_session.get(AiAutoDraft, draft_a.id).status == "dismissed"
    assert (
        db_session.query(AiAutoDraftTrigger)
        .filter(AiAutoDraftTrigger.tenant_id == tenant_a.id)
        .count()
        == 0
    )
    # Tenant B still has the thread visible, so its draft is untouched.
    assert db_session.get(AiAutoDraft, draft_b.id).status == "pending"


def test_open_thread_target_resolves_to_the_visible_tenant(non_admin_client, db_session):
    account = GmailAccount(email_address="open-target-account@example.com", is_active=True)
    hidden_tenant = Tenant(name="Hidden Tenant", booking_id="booking-open-target-hidden")
    visible_tenant = Tenant(name="Visible Tenant", booking_id="booking-open-target-visible")
    db_session.add_all([account, hidden_tenant, visible_tenant])
    db_session.flush()

    conversation = _make_conversation(db_session, account.id, "thread-open-target")
    _link(db_session, hidden_tenant.id, conversation.id, is_visible=False)
    _link(db_session, visible_tenant.id, conversation.id, is_visible=True)

    # A stale draft still points at the tenant that has since hidden the thread.
    db_session.add(
        AiAutoDraft(
            tenant_id=hidden_tenant.id, channel="email", email_thread_id=conversation.id,
            generated_text="stale draft", status="pending",
        )
    )
    db_session.commit()

    response = non_admin_client.get("/api/ai-auto-drafts", params={"tenant_id": hidden_tenant.id})
    assert response.status_code == 200
    payload = [d for d in response.json() if d["email_thread_id"] == conversation.id]
    assert len(payload) == 1
    draft = payload[0]
    assert draft["tenant_id"] == hidden_tenant.id
    # "Open thread" must route to the tenant that currently has the thread active, not the stored one.
    assert draft["open_thread_tenant_id"] == visible_tenant.id


def test_open_thread_target_is_the_stored_tenant_when_it_is_visible(non_admin_client, db_session):
    account = GmailAccount(email_address="open-target-single-account@example.com", is_active=True)
    tenant = Tenant(name="Solo Tenant", booking_id="booking-open-target-solo")
    db_session.add_all([account, tenant])
    db_session.flush()

    conversation = _make_conversation(db_session, account.id, "thread-open-target-solo")
    _link(db_session, tenant.id, conversation.id, is_visible=True)
    db_session.add(
        AiAutoDraft(
            tenant_id=tenant.id, channel="email", email_thread_id=conversation.id,
            generated_text="draft", status="pending",
        )
    )
    db_session.commit()

    response = non_admin_client.get("/api/ai-auto-drafts", params={"tenant_id": tenant.id})
    assert response.status_code == 200
    draft = next(d for d in response.json() if d["email_thread_id"] == conversation.id)
    assert draft["open_thread_tenant_id"] == tenant.id
