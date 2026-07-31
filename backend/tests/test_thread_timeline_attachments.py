from datetime import datetime, timezone

import pytest

from app.models.communication import Communication
from app.models.communication_attachment import CommunicationAttachment, CommunicationAttachmentLink
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.tenant_conversation_link import TenantConversationLink


@pytest.fixture(autouse=True)
def attachments_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_ROOT", str(tmp_path))
    yield tmp_path


def _store_attachment(db_session, tenant_id, filename, *, communication_id=None, conversation_message_id=None):
    attachment = CommunicationAttachment(
        tenant_id=tenant_id,
        storage_key=f"{tenant_id}/2026/07/{filename}",
        filename=filename,
        mime_type="application/pdf",
        size_bytes=123,
        sha256=f"sha-{filename}",
        origin="upload",
    )
    db_session.add(attachment)
    db_session.flush()
    db_session.add(
        CommunicationAttachmentLink(
            attachment_id=attachment.id,
            communication_id=communication_id,
            conversation_message_id=conversation_message_id,
            position=0,
        )
    )
    db_session.commit()
    return attachment


def test_stored_attachment_appears_on_an_email_timeline_message(non_admin_client, db_session):
    tenant = Tenant(name="Timeline Tenant", booking_id="B-tl-1", email="guest@example.com")
    account = GmailAccount(email_address="crm@example.com", is_active=True)
    db_session.add_all([tenant, account])
    db_session.flush()

    conversation = Conversation(
        provider="gmail", provider_account_id=account.id, provider_thread_id="thread-tl-1", subject="Booking"
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, source="email_match"))

    message = ConversationMessage(
        conversation_id=conversation.id,
        provider="gmail",
        provider_message_id="msg-tl-1",
        direction="outbound",
        sender_email="crm@example.com",
        recipient_email="guest@example.com",
        subject="Booking",
        body="Here is the contract.",
        sent_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        raw_payload={"gmail": {"id": "msg-tl-1"}},
    )
    db_session.add(message)
    db_session.commit()

    _store_attachment(db_session, tenant.id, "contract.pdf", conversation_message_id=message.id)

    response = non_admin_client.get(f"/api/communications/tenants/{tenant.id}/grouped-thread")
    assert response.status_code == 200

    thread = response.json()["items"][0]
    attachments = thread["messages"][0]["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "contract.pdf"
    assert attachments[0]["source"] == "stored"
    assert attachments[0]["attachment_id"].startswith("stored:")


def test_stored_attachment_appears_on_a_whatsapp_timeline_message(non_admin_client, db_session):
    tenant = Tenant(name="WA Timeline Tenant", booking_id="B-tl-2", phone="+31600000000")
    db_session.add(tenant)
    db_session.flush()
    db_session.add(
        TenantChannelEndpoint(
            tenant_id=tenant.id,
            channel_type="whatsapp",
            provider="whatsapp-service",
            external_account_id="edi-crm-whatsapp",
            external_chat_namespace="31612345678@c.us",
            is_active=True,
        )
    )
    communication = Communication(
        tenant_id=tenant.id,
        channel="whatsapp",
        direction="inbound",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="31612345678@c.us",
        whatsapp_chat_id="31612345678@c.us",
        provider_message_id="wa-tl-1",
        message="[Image]",
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    db_session.add(communication)
    db_session.commit()

    _store_attachment(db_session, tenant.id, "photo.png", communication_id=communication.id)

    response = non_admin_client.get(f"/api/communications/tenants/{tenant.id}/grouped-thread")
    assert response.status_code == 200

    group = response.json()["items"][0]
    assert group["type"] == "whatsapp_group"
    attachments = group["messages"][0]["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "photo.png"
    assert attachments[0]["source"] == "stored"


def test_gmail_derived_attachments_keep_their_source_and_merge_with_stored(non_admin_client, db_session):
    tenant = Tenant(name="Mixed Tenant", booking_id="B-tl-3", email="guest@example.com")
    account = GmailAccount(email_address="crm@example.com", is_active=True)
    db_session.add_all([tenant, account])
    db_session.flush()

    conversation = Conversation(
        provider="gmail", provider_account_id=account.id, provider_thread_id="thread-tl-3", subject="Mixed"
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, source="email_match"))

    message = ConversationMessage(
        conversation_id=conversation.id,
        provider="gmail",
        provider_message_id="msg-tl-3",
        direction="inbound",
        sender_email="guest@example.com",
        recipient_email="crm@example.com",
        subject="Mixed",
        body="Both kinds.",
        sent_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        raw_payload={
            "gmail": {"id": "msg-tl-3"},
            "attachments": [
                {"attachment_id": "gmail-att-9", "filename": "from-gmail.pdf", "mime_type": "application/pdf", "size": 7}
            ],
        },
    )
    db_session.add(message)
    db_session.commit()

    _store_attachment(db_session, tenant.id, "from-storage.pdf", conversation_message_id=message.id)

    response = non_admin_client.get(f"/api/communications/tenants/{tenant.id}/grouped-thread")
    attachments = response.json()["items"][0]["messages"][0]["attachments"]

    assert [item["filename"] for item in attachments] == ["from-gmail.pdf", "from-storage.pdf"]
    assert [item["source"] for item in attachments] == ["gmail", "stored"]
    # Ids must stay unique across the two namespaces so the frontend's React keys don't collide.
    assert len({item["attachment_id"] for item in attachments}) == 2


def test_message_without_attachments_reports_an_empty_list(non_admin_client, db_session):
    tenant = Tenant(name="Empty Tenant", booking_id="B-tl-4", phone="+31600000001")
    db_session.add(tenant)
    db_session.flush()
    db_session.add(
        TenantChannelEndpoint(
            tenant_id=tenant.id,
            channel_type="whatsapp",
            provider="whatsapp-service",
            external_account_id="edi-crm-whatsapp",
            external_chat_namespace="31699999999@c.us",
            is_active=True,
        )
    )
    db_session.add(
        Communication(
            tenant_id=tenant.id,
            channel="whatsapp",
            direction="inbound",
            provider="whatsapp-service",
            external_account_id="edi-crm-whatsapp",
            external_chat_namespace="31699999999@c.us",
            whatsapp_chat_id="31699999999@c.us",
            provider_message_id="wa-tl-4",
            message="Just text",
            created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    response = non_admin_client.get(f"/api/communications/tenants/{tenant.id}/grouped-thread")

    assert response.json()["items"][0]["messages"][0]["attachments"] == []
