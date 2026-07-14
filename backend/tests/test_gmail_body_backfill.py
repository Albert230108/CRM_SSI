import base64

from app.models.gmail_integration import Conversation, ConversationMessage


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _nested_gmail_message(message_id: str) -> dict:
    """A message whose plain-text body sits behind a nested multipart/alternative part.

    This shape (multipart/mixed > multipart/alternative > text/plain + text/html) is
    common for outbound mail carrying a signature, and used to make the old
    `_extract_text` return an empty string while `_extract_html` worked fine.
    """
    return {
        "id": message_id,
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "Re: House Search"}],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _encode("Hi there, sounds good.")}},
                        {"mimeType": "text/html", "body": {"data": _encode("<p>Hi there, sounds good.</p>")}},
                    ],
                },
                {"mimeType": "application/pdf", "body": {"attachmentId": "xyz"}},
            ],
        },
    }


def test_backfill_recovers_body_from_stored_raw_payload(client, db_session):
    conversation = Conversation(provider="gmail", provider_account_id=1, provider_thread_id="thread-1")
    db_session.add(conversation)
    db_session.flush()

    gmail_message = _nested_gmail_message("msg-1")
    stale_message = ConversationMessage(
        conversation_id=conversation.id,
        provider="gmail",
        provider_message_id="msg-1",
        direction="outbound",
        sender_email="info@shortstayinn.com",
        recipient_email="tenant@example.com",
        subject="Re: House Search",
        body="",
        sent_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        raw_payload={"gmail": gmail_message, "body_text": "", "body_html": ""},
    )
    db_session.add(stale_message)
    db_session.commit()

    response = client.post("/api/integrations/gmail/accounts/backfill-bodies")
    assert response.status_code == 200
    assert response.json() == {"scanned": 1, "updated": 1}

    db_session.refresh(stale_message)
    assert stale_message.body == "Hi there, sounds good."
    assert stale_message.raw_payload["body_html"] == "<p>Hi there, sounds good.</p>"


def test_backfill_skips_messages_without_stored_raw_gmail_payload(client, db_session):
    conversation = Conversation(provider="gmail", provider_account_id=1, provider_thread_id="thread-2")
    db_session.add(conversation)
    db_session.flush()

    manual_reply = ConversationMessage(
        conversation_id=conversation.id,
        provider="gmail",
        provider_message_id="msg-2",
        direction="outbound",
        sender_email="info@shortstayinn.com",
        recipient_email="tenant@example.com",
        subject="Re: House Search",
        body="Manually typed reply",
        sent_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        raw_payload={"gmail": {"id": "msg-2"}},
    )
    db_session.add(manual_reply)
    db_session.commit()

    response = client.post("/api/integrations/gmail/accounts/backfill-bodies")
    assert response.status_code == 200
    assert response.json() == {"scanned": 0, "updated": 0}

    db_session.refresh(manual_reply)
    assert manual_reply.body == "Manually typed reply"


def test_backfill_requires_admin(non_admin_client):
    response = non_admin_client.post("/api/integrations/gmail/accounts/backfill-bodies")
    assert response.status_code == 403
