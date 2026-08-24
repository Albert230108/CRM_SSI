import base64

import app.api.gmail_integration as gmail_integration
from app.database import SessionLocal
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _message(message_id: str, *, internal_date: str = "1700000000000", label_ids: list[str] | None = None) -> dict:
    message = {
        "id": message_id,
        "internalDate": internal_date,
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "tenant@example.com"},
                {"name": "To", "value": "account@example.com"},
                {"name": "Subject", "value": "Hello"},
            ],
            "body": {"data": _encode("Hi there")},
        },
    }
    if label_ids is not None:
        message["labelIds"] = label_ids
    return message


def _make_account(email: str) -> int:
    db = SessionLocal()
    try:
        account = GmailAccount(email_address=email, is_active=True)
        db.add(account)
        db.commit()
        return account.id
    finally:
        db.close()


def _cleanup(account_id: int, conversation_id: int | None, message_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        db.query(ConversationMessage).filter(ConversationMessage.provider_message_id.in_(message_ids)).delete(
            synchronize_session=False
        )
        if conversation_id is not None:
            db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        db.commit()
    finally:
        db.close()


def test_upsert_thread_survives_one_malformed_message_and_keeps_the_others():
    """Regression test: a single message that raises while being parsed (the thread's original
    message is often structured very differently than a plain-text reply) used to propagate out
    of _upsert_thread entirely, silently dropping every other message in the same thread too -
    and since the caller's history cursor advances regardless, those messages were never
    imported. Assert the good messages still get inserted even when one message is unparseable.
    """
    account_id = _make_account("resilience-account@example.com")
    thread = {
        "id": "thread-resilience",
        "messages": [
            _message("msg-bad", internal_date="not-a-valid-timestamp"),
            _message("msg-good-1"),
            _message("msg-good-2"),
        ],
    }

    db = SessionLocal()
    conversation_id = None
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()
        conversation_id = conversation.id

        good_ids = {
            row[0]
            for row in db.query(ConversationMessage.provider_message_id)
            .filter(ConversationMessage.provider_message_id.in_(["msg-good-1", "msg-good-2"]))
            .all()
        }
        assert good_ids == {"msg-good-1", "msg-good-2"}

        bad_exists = (
            db.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "msg-bad").first()
        )
        assert bad_exists is None
    finally:
        db.close()
        _cleanup(account_id, conversation_id, ["msg-bad", "msg-good-1", "msg-good-2"])


def test_upsert_thread_skips_draft_labeled_messages():
    """Regression test: Gmail's threads().get(format="full") includes a live draft's underlying
    message. Since Gmail assigns that message a new id on every edit/save, without filtering it
    would dodge the provider_message_id dedup check and be re-inserted as a new "sent" message on
    every draft save, showing up as duplicate stale snapshots in the tenant's thread.
    """
    account_id = _make_account("draft-filter-account@example.com")
    thread = {
        "id": "thread-draft-filter",
        "messages": [
            _message("msg-sent"),
            _message("msg-draft-v1", label_ids=["DRAFT"]),
        ],
    }

    db = SessionLocal()
    conversation_id = None
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = gmail_integration._upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()
        conversation_id = conversation.id

        sent_exists = (
            db.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "msg-sent").first()
        )
        assert sent_exists is not None

        draft_exists = (
            db.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "msg-draft-v1").first()
        )
        assert draft_exists is None
    finally:
        db.close()
        _cleanup(account_id, conversation_id, ["msg-sent", "msg-draft-v1"])
