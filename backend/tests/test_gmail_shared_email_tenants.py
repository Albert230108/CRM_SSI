import base64

import app.api.gmail_integration as gmail_integration
from app.database import SessionLocal
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.notification import Notification
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _message(message_id: str, from_address: str) -> dict:
    return {
        "id": message_id,
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": from_address},
                {"name": "To", "value": "shared-account@example.com"},
                {"name": "Subject", "value": "Booking question"},
            ],
            "body": {"data": _encode("Hi there")},
        },
    }


def test_two_tenants_sharing_an_email_both_keep_conversation_link():
    """Regression test: adding a second tenant with the same email must not steal an
    already-synced conversation away from the first tenant. Both tenants should end up
    with an active TenantConversationLink to the shared conversation.
    """
    shared_email = "shared-guest@example.com"

    setup_db = SessionLocal()
    try:
        account = GmailAccount(email_address="shared-account@example.com", is_active=True)
        old_tenant = Tenant(name="Old Tenant", email=shared_email, booking_id="booking-old-tenant")
        setup_db.add_all([account, old_tenant])
        setup_db.commit()
        account_id = account.id
        old_tenant_id = old_tenant.id
    finally:
        setup_db.close()

    # First sync: only the old tenant exists, so the conversation links to it.
    thread = {"id": "thread-shared-email", "messages": [_message("shared-msg-1", shared_email)]}
    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()
        conversation_id = conversation.id
        assert conversation.tenant_id == old_tenant_id
    finally:
        db.close()

    # A second tenant is added with the same email.
    db = SessionLocal()
    try:
        new_tenant = Tenant(name="New Tenant", email=shared_email, booking_id="booking-new-tenant")
        db.add(new_tenant)
        db.commit()
        new_tenant_id = new_tenant.id
    finally:
        db.close()

    # Second sync re-processes the same thread with a new message (e.g. background poller).
    thread = {
        "id": "thread-shared-email",
        "messages": [_message("shared-msg-1", shared_email), _message("shared-msg-2", shared_email)],
    }
    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()

        # The primary tenant_id must NOT be silently reassigned away from the old tenant.
        assert conversation.tenant_id == old_tenant_id

        active_links = (
            db.query(TenantConversationLink)
            .filter(TenantConversationLink.conversation_id == conversation_id)
            .filter(TenantConversationLink.unlinked_at.is_(None))
            .all()
        )
        linked_tenant_ids = {link.tenant_id for link in active_links}
        assert linked_tenant_ids == {old_tenant_id, new_tenant_id}
    finally:
        db.close()

    # Both tenants must see the conversation via the read endpoint's query.
    db = SessionLocal()
    try:
        for tenant_id in (old_tenant_id, new_tenant_id):
            conversations = (
                db.query(Conversation)
                .join(TenantConversationLink, TenantConversationLink.conversation_id == Conversation.id)
                .filter(TenantConversationLink.tenant_id == tenant_id)
                .filter(TenantConversationLink.unlinked_at.is_(None))
                .all()
            )
            assert any(c.id == conversation_id for c in conversations), f"tenant {tenant_id} lost visibility"
    finally:
        db.close()

    cleanup_db = SessionLocal()
    try:
        cleanup_db.query(Notification).filter(
            Notification.tenant_id.in_([old_tenant_id, new_tenant_id])
        ).delete(synchronize_session=False)
        cleanup_db.query(TenantConversationLink).filter(
            TenantConversationLink.conversation_id == conversation_id
        ).delete()
        cleanup_db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conversation_id
        ).delete()
        cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        cleanup_db.query(Tenant).filter(Tenant.id.in_([old_tenant_id, new_tenant_id])).delete(
            synchronize_session=False
        )
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()
