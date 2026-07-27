from datetime import datetime, timezone

import app.main as main_module
from app.database import SessionLocal
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount


def test_poll_continues_to_next_account_after_duplicate_key_error(monkeypatch):
    """Regression test for a background-poll crash.

    A concurrent sync path (e.g. the manual "sync all" endpoint) can insert a
    ConversationMessage with the same provider_message_id the background poller is
    about to insert, so the poller's commit fails with a UniqueViolation. The old
    exception handler then read `account.id` off the ORM object without rolling back
    first, which raised PendingRollbackError and aborted every account left in that
    poll cycle. Assert the loop now rolls back and keeps syncing later accounts.

    Uses real SessionLocal() calls (like the poller and the background thread it
    runs on do) instead of the request-scoped db_session fixture, since the bug only
    reproduces across independent sessions/transactions the way production sees it.
    """
    setup_db = SessionLocal()
    try:
        conversation = Conversation(provider="gmail", provider_account_id=1, provider_thread_id="thread-dup")
        setup_db.add(conversation)
        setup_db.flush()
        setup_db.add(
            ConversationMessage(
                conversation_id=conversation.id,
                provider="gmail",
                provider_message_id="dup-message",
                direction="inbound",
                sender_email="tenant@example.com",
                recipient_email="info@shortstayinn.com",
                subject="Hi",
                body="Hi",
                sent_at=datetime.now(timezone.utc),
                raw_payload={},
            )
        )
        account_a = GmailAccount(email_address="poll-test-a@example.com", is_active=True)
        account_b = GmailAccount(email_address="poll-test-b@example.com", is_active=True)
        setup_db.add_all([account_a, account_b])
        setup_db.commit()
        account_a_id = account_a.id
        account_b_id = account_b.id
        conversation_id = conversation.id
    finally:
        setup_db.close()

    synced_account_ids = []

    def fake_catch_up_gmail_account(db, account):
        synced_account_ids.append(account.id)
        if account.id == account_a_id:
            # Same provider_message_id another sync already committed - triggers the
            # UniqueViolation seen in production.
            db.add(
                ConversationMessage(
                    conversation_id=conversation_id,
                    provider="gmail",
                    provider_message_id="dup-message",
                    direction="inbound",
                    sender_email="tenant@example.com",
                    recipient_email="info@shortstayinn.com",
                    subject="Hi",
                    body="Hi",
                    sent_at=datetime.now(timezone.utc),
                    raw_payload={},
                )
            )
            db.commit()
        else:
            account.last_synced_at = datetime.now(timezone.utc)
            db.commit()

    monkeypatch.setattr(main_module, "_catch_up_gmail_account", fake_catch_up_gmail_account)

    try:
        main_module._poll_gmail_accounts_once()

        assert synced_account_ids == [account_a_id, account_b_id]

        verify_db = SessionLocal()
        try:
            refreshed_b = verify_db.get(GmailAccount, account_b_id)
            assert refreshed_b.last_synced_at is not None
        finally:
            verify_db.close()
    finally:
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conversation_id
            ).delete()
            cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
            cleanup_db.query(GmailAccount).filter(GmailAccount.id.in_([account_a_id, account_b_id])).delete(
                synchronize_session=False
            )
            cleanup_db.commit()
        finally:
            cleanup_db.close()
