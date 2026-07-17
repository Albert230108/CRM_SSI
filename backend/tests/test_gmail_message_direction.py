import base64

from app.api.gmail_integration import _message_direction, _upsert_thread
from app.database import SessionLocal
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def test_message_direction_prefers_gmail_labels_over_sender_header():
    """Regression test: a guest replying through an alias, Send-As address, or shared
    support inbox can have a From header that matches the CRM's own account address even
    though the message actually landed in INBOX. Gmail's own SENT/INBOX labels are
    authoritative and must win over the sender-email string comparison."""
    message = {"labelIds": ["INBOX", "UNREAD"]}
    assert _message_direction(message, sender_email="crm@example.com", account_email="crm@example.com") == "inbound"

    message = {"labelIds": ["SENT"]}
    assert _message_direction(message, sender_email="guest@example.com", account_email="crm@example.com") == "outbound"


def test_message_direction_falls_back_to_sender_header_without_labels():
    message = {}
    assert _message_direction(message, sender_email="crm@example.com", account_email="crm@example.com") == "outbound"
    assert _message_direction(message, sender_email="guest@example.com", account_email="crm@example.com") == "inbound"


def test_upsert_thread_classifies_inbox_labeled_message_as_inbound_despite_matching_sender():
    """End-to-end regression: same account-address-in-From scenario, run through
    _upsert_thread, confirming the persisted ConversationMessage.direction follows the
    Gmail label rather than the sender-email heuristic."""
    account = GmailAccount(email_address="support@example.com", is_active=True)
    setup_db = SessionLocal()
    try:
        setup_db.add(account)
        setup_db.commit()
        account_id = account.id
    finally:
        setup_db.close()

    thread = {
        "id": "thread-alias",
        "messages": [
            {
                "id": "msg-alias",
                "internalDate": "1700000000000",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "support@example.com"},
                        {"name": "To", "value": "support@example.com"},
                        {"name": "Subject", "value": "Reply via shared alias"},
                    ],
                    "body": {"data": _encode("Guest reply forwarded through the shared alias")},
                },
            }
        ],
    }

    db = SessionLocal()
    try:
        account_obj = db.get(GmailAccount, account_id)
        conversation = _upsert_thread(db, account_obj, thread)
        assert conversation is not None
        db.commit()

        saved = db.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "msg-alias").one()
        assert saved.direction == "inbound"

        conversation_id = conversation.id
    finally:
        db.close()

    cleanup_db = SessionLocal()
    try:
        cleanup_db.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "msg-alias").delete()
        cleanup_db.query(Conversation).filter(Conversation.id == conversation_id).delete()
        cleanup_db.query(GmailAccount).filter(GmailAccount.id == account_id).delete()
        cleanup_db.commit()
    finally:
        cleanup_db.close()
