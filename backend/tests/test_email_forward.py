from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.admin_settings import AdminSettings
from app.models.communication import Communication
from app.models.communication_attachment import CommunicationAttachment, CommunicationAttachmentLink
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink


@pytest.fixture(autouse=True)
def attachments_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_ROOT", str(tmp_path))
    yield tmp_path


def _setup_thread(db_session, forward_to_email="ai-drafts@example.com"):
    tenant = Tenant(name="Forward Tenant", booking_id="B-fwd-1", email="tenant@example.com")
    account = GmailAccount(email_address="crm@example.com", is_active=True, refresh_token_encrypted="enc-token")
    db_session.add_all([tenant, account])
    db_session.flush()

    conversation = Conversation(
        provider="gmail", provider_account_id=account.id, provider_thread_id="thread-fwd-1", subject="Booking question"
    )
    db_session.add(conversation)
    db_session.flush()

    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, source="email_match"))

    db_session.add_all(
        [
            ConversationMessage(
                conversation_id=conversation.id,
                provider="gmail",
                provider_message_id="msg-1",
                direction="inbound",
                sender_email="tenant@example.com",
                recipient_email="crm@example.com",
                subject="Booking question",
                body="Hi, can I check in early?",
                sent_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                raw_payload={"gmail": {"payload": {"headers": [{"name": "Message-ID", "value": "<msg-1@mail>"}]}}},
            ),
            ConversationMessage(
                conversation_id=conversation.id,
                provider="gmail",
                provider_message_id="msg-2",
                direction="outbound",
                sender_email="crm@example.com",
                recipient_email="tenant@example.com",
                subject="Re: Booking question",
                body="Sure, early check-in is fine.",
                sent_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
                raw_payload={
                    "gmail": {
                        "payload": {
                            "headers": [
                                {"name": "Message-ID", "value": "<msg-2@mail>"},
                                {"name": "References", "value": "<msg-1@mail>"},
                            ]
                        }
                    }
                },
            ),
        ]
    )

    if forward_to_email:
        db_session.add(AdminSettings(forward_to_email=forward_to_email))

    db_session.commit()
    db_session.refresh(tenant)
    db_session.refresh(conversation)
    return tenant, conversation, account


@patch("app.api.communications._build_gmail_credentials")
@patch("app.api.communications.send_gmail_forward")
def test_forward_composes_quoted_thread_and_persists(mock_send_forward, mock_build_credentials, non_admin_client, db_session):
    tenant, conversation, account = _setup_thread(db_session)
    mock_build_credentials.return_value = object()
    mock_send_forward.return_value = {"id": "sent-forward-1"}

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/forward",
        json={"email_thread_id": conversation.id, "body": "Please review and reply."},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["channel"] == "email"
    assert data["message"] == "Please review and reply."

    assert mock_send_forward.call_count == 1
    _, kwargs = mock_send_forward.call_args
    assert kwargs["thread_id"] == "thread-fwd-1"
    assert kwargs["to_email"] == "ai-drafts@example.com"
    assert kwargs["subject"] == "Booking question"
    assert kwargs["in_reply_to_message_id"] == "<msg-2@mail>"
    assert kwargs["references"] == "<msg-1@mail>"
    assert kwargs["body_text"].startswith("Please review and reply.")
    assert "---------- Forwarded message ----------" in kwargs["body_text"]
    assert "Hi, can I check in early?" in kwargs["body_text"]
    assert "Sure, early check-in is fine." in kwargs["body_text"]

    persisted = (
        db_session.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.id.desc())
        .first()
    )
    assert persisted.direction == "outbound"
    assert persisted.recipient_email == "ai-drafts@example.com"
    assert persisted.provider_message_id == "sent-forward-1"

    communication = (
        db_session.query(Communication)
        .filter(Communication.tenant_id == tenant.id)
        .order_by(Communication.id.desc())
        .first()
    )
    assert communication.message == "Please review and reply."
    assert communication.channel == "email"


@patch("app.api.communications._build_gmail_credentials")
def test_forward_requires_configured_address(mock_build_credentials, non_admin_client, db_session):
    tenant, conversation, account = _setup_thread(db_session, forward_to_email=None)
    mock_build_credentials.return_value = object()

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/forward",
        json={"email_thread_id": conversation.id, "body": "Hello"},
    )
    assert response.status_code == 400
    assert "Admin Settings" in response.json()["detail"]


def _attach_gmail_metadata(db_session, conversation, filename="contract.pdf", attachment_id="gmail-att-1"):
    """Give the thread's inbound message a Gmail attachment, metadata-only as the sync stores it."""
    message = (
        db_session.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.id.asc())
        .first()
    )
    payload = dict(message.raw_payload or {})
    payload["attachments"] = [
        {"attachment_id": attachment_id, "filename": filename, "mime_type": "application/pdf", "size": 11}
    ]
    message.raw_payload = payload
    db_session.commit()
    return message


@patch("app.api.communications._build_gmail_credentials")
@patch("app.api.communications.send_gmail_forward")
def test_forward_carries_selected_original_attachments(
    mock_send_forward, mock_build_credentials, non_admin_client, db_session
):
    tenant, conversation, account = _setup_thread(db_session)
    mock_build_credentials.return_value = object()
    mock_send_forward.return_value = {"id": "sent-forward-2"}
    source_message = _attach_gmail_metadata(db_session, conversation)

    with patch("app.api.communications.fetch_gmail_attachment_bytes") as mock_fetch:
        mock_fetch.return_value = (b"pdf-content", "contract.pdf", "application/pdf")
        response = non_admin_client.post(
            f"/api/communications/tenants/{tenant.id}/forward",
            json={
                "email_thread_id": conversation.id,
                "body": "Please review.",
                "include_original_attachment_ids": [f"{source_message.id}:gmail-att-1"],
            },
        )

    assert response.status_code == 201
    _, kwargs = mock_send_forward.call_args
    sent = kwargs["attachments"]
    assert len(sent) == 1
    assert sent[0].filename == "contract.pdf"
    assert sent[0].content == b"pdf-content"

    # The fetched blob is stored so the sent forward renders its own attachments and the file
    # becomes re-attachable from history.
    stored = db_session.query(CommunicationAttachment).filter_by(tenant_id=tenant.id).one()
    assert stored.origin == "gmail"
    links = db_session.query(CommunicationAttachmentLink).filter_by(attachment_id=stored.id).all()
    assert len(links) == 2, "expected links to both the ConversationMessage and the Communication"
    assert {link.communication_id is not None for link in links} == {True, False}


@patch("app.api.communications._build_gmail_credentials")
@patch("app.api.communications.send_gmail_forward")
def test_forward_without_selected_attachments_sends_none(
    mock_send_forward, mock_build_credentials, non_admin_client, db_session
):
    tenant, conversation, account = _setup_thread(db_session)
    mock_build_credentials.return_value = object()
    mock_send_forward.return_value = {"id": "sent-forward-3"}
    _attach_gmail_metadata(db_session, conversation)

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/forward",
        json={"email_thread_id": conversation.id, "body": "No files please."},
    )

    assert response.status_code == 201
    _, kwargs = mock_send_forward.call_args
    assert list(kwargs["attachments"]) == []
    assert db_session.query(CommunicationAttachment).filter_by(tenant_id=tenant.id).count() == 0


@patch("app.api.communications._build_gmail_credentials")
@patch("app.api.communications.send_gmail_forward")
def test_forward_notes_attachments_omitted_for_exceeding_the_cap(
    mock_send_forward, mock_build_credentials, non_admin_client, db_session, monkeypatch
):
    monkeypatch.setenv("ATTACHMENT_MAX_EMAIL_MESSAGE_BYTES", "5")
    tenant, conversation, account = _setup_thread(db_session)
    mock_build_credentials.return_value = object()
    mock_send_forward.return_value = {"id": "sent-forward-4"}
    source_message = _attach_gmail_metadata(db_session, conversation)

    with patch("app.api.communications.fetch_gmail_attachment_bytes") as mock_fetch:
        mock_fetch.return_value = (b"far too many bytes", "contract.pdf", "application/pdf")
        response = non_admin_client.post(
            f"/api/communications/tenants/{tenant.id}/forward",
            json={
                "email_thread_id": conversation.id,
                "body": "Please review.",
                "include_original_attachment_ids": [f"{source_message.id}:gmail-att-1"],
            },
        )

    assert response.status_code == 201
    _, kwargs = mock_send_forward.call_args
    assert list(kwargs["attachments"]) == []
    # Overflow must be visible in the body, not silently dropped.
    assert "1 attachment(s) omitted" in kwargs["body_text"]


@patch("app.api.communications._build_gmail_credentials")
@patch("app.api.communications.send_gmail_forward")
def test_forward_rejects_an_attachment_reference_from_another_thread(
    mock_send_forward, mock_build_credentials, non_admin_client, db_session
):
    tenant, conversation, account = _setup_thread(db_session)
    mock_build_credentials.return_value = object()
    mock_send_forward.return_value = {"id": "sent-forward-5"}

    response = non_admin_client.post(
        f"/api/communications/tenants/{tenant.id}/forward",
        json={
            "email_thread_id": conversation.id,
            "body": "Please review.",
            "include_original_attachment_ids": ["999999:gmail-att-1"],
        },
    )

    assert response.status_code == 400
    assert mock_send_forward.call_count == 0
