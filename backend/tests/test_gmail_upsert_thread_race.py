import base64

import app.api.gmail_integration as gmail_integration
from app.api.gmail_integration import PROVIDER_GMAIL
from app.database import SessionLocal
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _message(message_id: str) -> dict:
    return {
        "id": message_id,
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "racer-tenant@example.com"},
                {"name": "To", "value": "racer-account@example.com"},
                {"name": "Subject", "value": "Hello"},
            ],
            "body": {"data": _encode("Hi there")},
        },
    }


def test_upsert_thread_survives_duplicate_message_id_in_same_batch():
    """Regression test for the UniqueViolation that crashed the background Gmail poller.

    _sync_gmail_account/SessionLocal use autoflush=False, so the dedup query in
    _upsert_thread ("does a ConversationMessage with this provider_message_id already
    exist?") does not see an insert that's merely pending in this same session - only
    one that has actually been flushed. If the same message id shows up twice within
    one sync call (e.g. Gmail returning it across two overlapping threads/history
    records, which mirrors the concurrent-sync race from the original bug report),
    both occurrences pass the dedup check and both get queued for insert, so the
    eventual commit fails with a UniqueViolation. Before the fix, that exception
    wasn't scoped to the one message, and propagated out of _upsert_thread entirely.
    Assert it now stays contained: only one row is persisted, and the conversation
    update completes and commits normally.
    """
    account = GmailAccount(email_address="racer-account@example.com", is_active=True)
    setup_db = SessionLocal()
    try:
        setup_db.add(account)
        setup_db.commit()
        account_id = account.id
    finally:
        setup_db.close()

    thread = {"id": "thread-race", "messages": [_message("dup-msg"), _message("dup-msg")]}

    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()

        matches = (
            db.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "dup-msg").all()
        )
        assert len(matches) == 1
        assert conversation.subject == "Hello"

        conversation_id = conversation.id
    finally:
        db.close()

    cleanup_db = SessionLocal()
    try:
        cleanup_db.query(ConversationMessage).filter(
            ConversationMessage.provider_message_id == "dup-msg"
        ).delete()
        cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()


def test_upsert_thread_converges_on_a_single_conversation_when_creation_races(monkeypatch):
    """Regression test for the thread-splitting race this migration/uniqueness-constraint pair
    fixes: two overlapping syncs (e.g. a Pub/Sub push landing while the catch-up poller is
    mid-run) could both find no existing Conversation for a brand-new thread and both create one,
    stranding messages across two orphaned rows - most visibly, a thread's original message
    ending up on the row that never gets linked/shown.

    Simulates the race by having _find_existing_conversation_for_thread's "nothing found yet"
    return also be the moment another session wins: it inserts and commits a conflicting
    Conversation row as a side effect, mirroring a concurrent sync that got there first. The
    conversations.uq_conversations_provider_account_thread constraint must then reject this
    session's own insert, and _upsert_thread must recover by using the row that won instead of
    leaving this sync's message stranded.
    """
    account = GmailAccount(email_address="race-thread-account@example.com", is_active=True)
    setup_db = SessionLocal()
    try:
        setup_db.add(account)
        setup_db.commit()
        account_id = account.id
    finally:
        setup_db.close()

    winner_conversation_id: list[int] = []
    original_finder = gmail_integration._find_existing_conversation_for_thread

    def racing_finder(db, thread):
        result = original_finder(db, thread)
        if result is None and not winner_conversation_id:
            other_session = SessionLocal()
            try:
                other_conversation = Conversation(
                    provider=PROVIDER_GMAIL, provider_account_id=account_id, provider_thread_id="thread-split-race"
                )
                other_session.add(other_conversation)
                other_session.commit()
                winner_conversation_id.append(other_conversation.id)
            finally:
                other_session.close()
        return result

    monkeypatch.setattr(gmail_integration, "_find_existing_conversation_for_thread", racing_finder)

    thread = {"id": "thread-split-race", "messages": [_message("race-msg")]}

    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()

        assert winner_conversation_id, "test setup did not trigger the simulated race"
        assert conversation.id == winner_conversation_id[0]

        matching_conversations = (
            db.query(Conversation)
            .filter(
                Conversation.provider == PROVIDER_GMAIL,
                Conversation.provider_account_id == account_id,
                Conversation.provider_thread_id == "thread-split-race",
            )
            .all()
        )
        assert len(matching_conversations) == 1

        message = (
            db.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "race-msg").first()
        )
        assert message is not None
        assert message.conversation_id == winner_conversation_id[0]

        conversation_id = conversation.id
    finally:
        db.close()

    cleanup_db = SessionLocal()
    try:
        cleanup_db.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "race-msg").delete()
        cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()
