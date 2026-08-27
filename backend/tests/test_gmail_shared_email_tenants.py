import base64

import app.api.gmail_integration as gmail_integration
from app.database import SessionLocal
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.action_writer_trigger import ActionWriterTrigger
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_brain_trigger import TenantBrainTrigger
from app.models.notification import Notification
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant_email_address import TenantEmailAddress


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _link_email(db, tenant_id: int, email: str) -> None:
    """Make `tenant_id` reachable at `email`.

    Matching is by CRM_EMAIL link only now, so setting Tenant.email no longer routes any
    mail; these tests express reachability the way the product does.
    """
    db.add(TenantEmailAddress(tenant_id=tenant_id, email=email, is_active=True))
    db.commit()


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
        _link_email(setup_db, old_tenant_id, shared_email)
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
        _link_email(db, new_tenant_id, shared_email)
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
        cleanup_db.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id.in_([old_tenant_id, new_tenant_id])).delete(synchronize_session=False)
        cleanup_db.query(Tenant).filter(Tenant.id.in_([old_tenant_id, new_tenant_id])).delete(
            synchronize_session=False
        )
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()


def test_hidden_shared_thread_skips_notifications_and_triggers():
    shared_email = "hidden-shared@example.com"
    thread_id = "thread-hidden-shared"

    setup_db = SessionLocal()
    try:
        account = GmailAccount(email_address="hidden-shared-account@example.com", is_active=True)
        visible_tenant = Tenant(name="Visible Tenant", email=shared_email, booking_id="booking-hidden-visible")
        hidden_tenant = Tenant(
            name="Hidden Tenant",
            email=shared_email,
            booking_id="booking-hidden-hidden",
            auto_add_shared_email_threads=False,
        )
        setup_db.add_all([account, visible_tenant, hidden_tenant])
        setup_db.commit()
        account_id = account.id
        visible_tenant_id = visible_tenant.id
        hidden_tenant_id = hidden_tenant.id
        _link_email(setup_db, visible_tenant_id, shared_email)
        _link_email(setup_db, hidden_tenant_id, shared_email)
        setup_db.add_all(
            [
                TenantAiSettings(tenant_id=visible_tenant_id, auto_draft_email=True),
                TenantAiSettings(tenant_id=hidden_tenant_id, auto_draft_email=True),
            ]
        )
        setup_db.commit()
        setup_db.add(Conversation(provider="gmail", provider_account_id=account_id, provider_thread_id=thread_id))
        setup_db.commit()
        conversation_id = setup_db.query(Conversation).filter(Conversation.provider_thread_id == thread_id).one().id
        setup_db.add(
            TenantConversationLink(
                tenant_id=hidden_tenant_id,
                conversation_id=conversation_id,
                matched_email=shared_email,
                is_visible=False,
            )
        )
        setup_db.commit()
    finally:
        setup_db.close()

    thread = {"id": thread_id, "messages": [_message("hidden-shared-msg-1", shared_email)]}
    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()

        assert db.query(Notification).filter(Notification.tenant_id == hidden_tenant_id).count() == 0
        assert db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == hidden_tenant_id).count() == 0
        assert db.query(Notification).filter(Notification.tenant_id == visible_tenant_id).count() == 1
        assert db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == visible_tenant_id).count() == 1
    finally:
        db.close()

    cleanup_db = SessionLocal()
    try:
        cleanup_db.query(Notification).filter(Notification.tenant_id.in_([visible_tenant_id, hidden_tenant_id])).delete(synchronize_session=False)
        cleanup_db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id.in_([visible_tenant_id, hidden_tenant_id])).delete(synchronize_session=False)
        cleanup_db.query(TenantConversationLink).filter(TenantConversationLink.conversation_id == conversation_id).delete()
        cleanup_db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).delete()
        cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        cleanup_db.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id.in_([visible_tenant_id, hidden_tenant_id])).delete(synchronize_session=False)
        cleanup_db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id.in_([visible_tenant_id, hidden_tenant_id])).delete(synchronize_session=False)
        cleanup_db.query(Tenant).filter(Tenant.id.in_([visible_tenant_id, hidden_tenant_id])).delete(synchronize_session=False)
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()



def test_shared_thread_second_message_notifies_all_visible_tenants_without_widening_ai_triggers():
    """A visible shared thread should notify every tenant that already has access, even if
    the current inbound message's headers only mention one of them.

    AI trigger scope stays header-based: only the tenant actually addressed by the new
    message should get its debounced AI rows refreshed.
    """
    tenant_a_email = "tenant-a@example.com"
    tenant_b_email = "tenant-b@example.com"
    relay_email = "relay@example.com"
    conversation_id = None

    setup_db = SessionLocal()
    try:
        account = GmailAccount(email_address="shared-notify-account@example.com", is_active=True)
        tenant_a = Tenant(name="Tenant A", booking_id="booking-shared-notify-a")
        tenant_b = Tenant(name="Tenant B", booking_id="booking-shared-notify-b")
        setup_db.add_all([account, tenant_a, tenant_b])
        setup_db.commit()
        account_id = account.id
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        _link_email(setup_db, tenant_a_id, tenant_a_email)
        _link_email(setup_db, tenant_b_id, tenant_b_email)
        setup_db.add_all(
            [
                TenantAiSettings(
                    tenant_id=tenant_a_id,
                    auto_draft_email=True,
                    brain_writer_enabled=True,
                    action_writer_enabled=True,
                ),
                TenantAiSettings(
                    tenant_id=tenant_b_id,
                    auto_draft_email=True,
                    brain_writer_enabled=True,
                    action_writer_enabled=True,
                ),
            ]
        )
        setup_db.commit()
    finally:
        setup_db.close()

    def _thread_message(message_id: str, recipients: list[str]) -> dict:
        message = _message(message_id, relay_email)
        message["payload"]["headers"] = [
            {"name": "From", "value": relay_email},
            {"name": "To", "value": ", ".join(recipients)},
            {"name": "Subject", "value": "Booking question"},
        ]
        return message

    thread = {"id": "thread-shared-notify", "messages": [_thread_message("shared-notify-msg-1", [tenant_a_email, tenant_b_email])]}
    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()
        conversation_id = conversation.id

        assert db.query(Notification).filter(Notification.tenant_id == tenant_a_id, Notification.thread_ref == str(conversation_id)).count() == 1
        assert db.query(Notification).filter(Notification.tenant_id == tenant_b_id, Notification.thread_ref == str(conversation_id)).count() == 1

        tenant_a_auto_before = (
            db.query(AiAutoDraftTrigger)
            .filter(AiAutoDraftTrigger.tenant_id == tenant_a_id, AiAutoDraftTrigger.channel == "email")
            .one()
        )
        tenant_b_auto_before = (
            db.query(AiAutoDraftTrigger)
            .filter(AiAutoDraftTrigger.tenant_id == tenant_b_id, AiAutoDraftTrigger.channel == "email")
            .one()
        )
        tenant_b_brain_before = (
            db.query(TenantBrainTrigger)
            .filter(TenantBrainTrigger.tenant_id == tenant_b_id, TenantBrainTrigger.channel == "email")
            .one()
        )
        tenant_b_action_before = (
            db.query(ActionWriterTrigger)
            .filter(ActionWriterTrigger.tenant_id == tenant_b_id, ActionWriterTrigger.channel == "email")
            .one()
        )
    finally:
        db.close()

    thread = {
        "id": "thread-shared-notify",
        "messages": [
            _thread_message("shared-notify-msg-1", [tenant_a_email, tenant_b_email]),
            _thread_message("shared-notify-msg-2", [tenant_a_email]),
        ],
    }
    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()
        conversation_id = conversation.id

        assert db.query(Notification).filter(Notification.tenant_id == tenant_a_id, Notification.thread_ref == str(conversation_id)).count() == 2
        assert db.query(Notification).filter(Notification.tenant_id == tenant_b_id, Notification.thread_ref == str(conversation_id)).count() == 2

        tenant_b_auto_after = (
            db.query(AiAutoDraftTrigger)
            .filter(AiAutoDraftTrigger.tenant_id == tenant_b_id, AiAutoDraftTrigger.channel == "email")
            .one()
        )
        tenant_b_brain_after = (
            db.query(TenantBrainTrigger)
            .filter(TenantBrainTrigger.tenant_id == tenant_b_id, TenantBrainTrigger.channel == "email")
            .one()
        )
        tenant_b_action_after = (
            db.query(ActionWriterTrigger)
            .filter(ActionWriterTrigger.tenant_id == tenant_b_id, ActionWriterTrigger.channel == "email")
            .one()
        )

        assert tenant_b_auto_after.trigger_at == tenant_b_auto_before.trigger_at
        assert tenant_b_brain_after.trigger_at == tenant_b_brain_before.trigger_at
        assert tenant_b_action_after.trigger_at == tenant_b_action_before.trigger_at
        assert (
            db.query(AiAutoDraftTrigger)
            .filter(AiAutoDraftTrigger.tenant_id == tenant_a_id, AiAutoDraftTrigger.channel == "email")
            .one()
            .trigger_at
            >= tenant_a_auto_before.trigger_at
        )
    finally:
        db.close()

    cleanup_db = SessionLocal()
    try:
        cleanup_db.query(Notification).filter(Notification.thread_ref == str(conversation_id)).delete(synchronize_session=False)
        cleanup_db.query(TenantConversationLink).filter(TenantConversationLink.conversation_id == conversation_id).delete()
        cleanup_db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).delete()
        cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        cleanup_db.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id.in_([tenant_a_id, tenant_b_id])).delete(synchronize_session=False)
        cleanup_db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id.in_([tenant_a_id, tenant_b_id])).delete(synchronize_session=False)
        cleanup_db.query(TenantBrainTrigger).filter(TenantBrainTrigger.tenant_id.in_([tenant_a_id, tenant_b_id])).delete(synchronize_session=False)
        cleanup_db.query(ActionWriterTrigger).filter(ActionWriterTrigger.tenant_id.in_([tenant_a_id, tenant_b_id])).delete(synchronize_session=False)
        cleanup_db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id.in_([tenant_a_id, tenant_b_id])).delete(synchronize_session=False)
        cleanup_db.query(Tenant).filter(Tenant.id.in_([tenant_a_id, tenant_b_id])).delete(synchronize_session=False)
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
        _link_email(setup_db, tenant_id, primary_email)
        _link_email(setup_db, tenant_id, secondary_email)
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
        cleanup_db.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant_id).delete(synchronize_session=False)
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
        _link_email(setup_db, tenant_id, mixed_case_email)
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
        cleanup_db.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant_id).delete(synchronize_session=False)
        cleanup_db.query(Tenant).filter(Tenant.id == tenant_id).delete()
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()


def test_new_link_respects_tenant_auto_add_preference():
    """A tenant with auto_add_shared_email_threads=False must still get linked to a newly
    matched conversation (it keeps access/history), but the link starts hidden (is_visible=False)
    until manually toggled on -- versus the default (auto_add=True) tenant, whose link stays
    visible like before this preference existed.
    """
    shared_email = "auto-add-pref@example.com"

    setup_db = SessionLocal()
    try:
        account = GmailAccount(email_address="auto-add-account@example.com", is_active=True)
        default_tenant = Tenant(name="Default Tenant", email=shared_email, booking_id="booking-auto-add-default")
        opted_out_tenant = Tenant(
            name="Opted Out Tenant",
            email=shared_email,
            booking_id="booking-auto-add-off",
            auto_add_shared_email_threads=False,
        )
        setup_db.add_all([account, default_tenant, opted_out_tenant])
        setup_db.commit()
        account_id = account.id
        default_tenant_id = default_tenant.id
        opted_out_tenant_id = opted_out_tenant.id
        _link_email(setup_db, default_tenant_id, shared_email)
        _link_email(setup_db, opted_out_tenant_id, shared_email)
    finally:
        setup_db.close()

    thread = {"id": "thread-auto-add-pref", "messages": [_message("auto-add-msg-1", shared_email)]}
    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()
        conversation_id = conversation.id

        default_link = (
            db.query(TenantConversationLink)
            .filter(TenantConversationLink.tenant_id == default_tenant_id, TenantConversationLink.conversation_id == conversation_id)
            .first()
        )
        opted_out_link = (
            db.query(TenantConversationLink)
            .filter(TenantConversationLink.tenant_id == opted_out_tenant_id, TenantConversationLink.conversation_id == conversation_id)
            .first()
        )
        default_notification_count = db.query(Notification).filter(Notification.tenant_id == default_tenant_id).count()
        opted_out_notification_count = db.query(Notification).filter(Notification.tenant_id == opted_out_tenant_id).count()
        assert default_link is not None and default_link.is_visible is True
        assert opted_out_link is not None and opted_out_link.is_visible is False
        assert default_notification_count == 1
        assert opted_out_notification_count == 0
    finally:
        db.close()

    cleanup_db = SessionLocal()
    try:
        cleanup_db.query(Notification).filter(
            Notification.tenant_id.in_([default_tenant_id, opted_out_tenant_id])
        ).delete(synchronize_session=False)
        cleanup_db.query(TenantConversationLink).filter(TenantConversationLink.conversation_id == conversation_id).delete()
        cleanup_db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).delete()
        cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        cleanup_db.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id.in_([default_tenant_id, opted_out_tenant_id])).delete(synchronize_session=False)
        cleanup_db.query(Tenant).filter(Tenant.id.in_([default_tenant_id, opted_out_tenant_id])).delete(synchronize_session=False)
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()
