import base64

import app.api.gmail_integration as gmail_integration
from app.database import SessionLocal
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.notification import Notification
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant_email_address import TenantEmailAddress


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


def test_tenant_matched_via_secondary_linked_email():
    """A tenant with no matching Tenant.email should still be resolved for an inbound
    message when the sender address only matches one of their linked TenantEmailAddress
    rows, not the primary email column."""
    primary_email = "primary-guest@example.com"
    secondary_email = "secondary-guest@example.com"

    setup_db = SessionLocal()
    try:
        account = GmailAccount(email_address="shared-account-2@example.com", is_active=True)
        tenant = Tenant(name="Secondary Email Tenant", email=primary_email, booking_id="booking-secondary-email")
        setup_db.add_all([account, tenant])
        setup_db.commit()
        account_id = account.id
        tenant_id = tenant.id
        setup_db.add(TenantEmailAddress(tenant_id=tenant_id, email=secondary_email, is_active=True))
        setup_db.commit()
    finally:
        setup_db.close()

    thread = {"id": "thread-secondary-email", "messages": [_message("secondary-msg-1", secondary_email)]}
    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()
        conversation_id = conversation.id
        assert conversation.tenant_id == tenant_id

        # Regression test: the link's matched_email must record the secondary address that
        # actually matched, not the tenant's primary email -- otherwise unlinking the secondary
        # email later can never find (and delete) this conversation, and the UI misreports which
        # address the conversation belongs to.
        link = (
            db.query(TenantConversationLink)
            .filter(TenantConversationLink.tenant_id == tenant_id, TenantConversationLink.conversation_id == conversation_id)
            .first()
        )
        assert link is not None
        assert link.matched_email == secondary_email
    finally:
        db.close()

    cleanup_db = SessionLocal()
    try:
        cleanup_db.query(Notification).filter(Notification.tenant_id == tenant_id).delete(synchronize_session=False)
        cleanup_db.query(TenantConversationLink).filter(TenantConversationLink.conversation_id == conversation_id).delete()
        cleanup_db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).delete()
        cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        cleanup_db.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant_id).delete()
        cleanup_db.query(Tenant).filter(Tenant.id == tenant_id).delete()
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()


def test_tenant_matched_when_primary_email_has_different_case():
    """Regression test: Tenant.email is stored exactly as Beds24/manual entry provided it
    (no lowercasing), but Gmail header addresses are always lowercased before matching. A
    tenant whose primary email happens to contain uppercase characters must still be matched
    and linked, instead of silently never getting a TenantConversationLink.
    """
    mixed_case_email = "John.Doe@Example.com"
    incoming_header_address = "john.doe@example.com"

    setup_db = SessionLocal()
    try:
        account = GmailAccount(email_address="case-account@example.com", is_active=True)
        tenant = Tenant(name="Case Tenant", email=mixed_case_email, booking_id="booking-case-tenant")
        setup_db.add_all([account, tenant])
        setup_db.commit()
        account_id = account.id
        tenant_id = tenant.id
    finally:
        setup_db.close()

    thread = {"id": "thread-case-email", "messages": [_message("case-msg-1", incoming_header_address)]}
    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()
        conversation_id = conversation.id
        assert conversation.tenant_id == tenant_id

        link = (
            db.query(TenantConversationLink)
            .filter(TenantConversationLink.tenant_id == tenant_id, TenantConversationLink.conversation_id == conversation_id)
            .filter(TenantConversationLink.unlinked_at.is_(None))
            .first()
        )
        assert link is not None
    finally:
        db.close()

    cleanup_db = SessionLocal()
    try:
        cleanup_db.query(Notification).filter(Notification.tenant_id == tenant_id).delete(synchronize_session=False)
        cleanup_db.query(TenantConversationLink).filter(TenantConversationLink.conversation_id == conversation_id).delete()
        cleanup_db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).delete()
        cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        cleanup_db.query(Tenant).filter(Tenant.id == tenant_id).delete()
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()
