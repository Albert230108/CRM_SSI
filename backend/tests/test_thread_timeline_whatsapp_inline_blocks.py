from datetime import datetime, timedelta, timezone

from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.services.thread_timeline_service import build_tenant_thread_timeline


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def add_email_conversation(db_session, tenant_id, *, subject, message_times):
    conversation = Conversation(
        provider="gmail",
        provider_thread_id=f"thread-{tenant_id}-{subject}",
        tenant_id=tenant_id,
        subject=subject,
        last_message_at=message_times[-1],
    )
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)

    for index, sent_at in enumerate(message_times):
        db_session.add(
            ConversationMessage(
                conversation_id=conversation.id,
                provider="gmail",
                provider_message_id=f"msg-{conversation.id}-{index}",
                direction="inbound" if index % 2 == 0 else "outbound",
                sender_email="guest@example.com",
                recipient_email="host@example.com",
                subject=subject,
                body=f"Body {index}",
                sent_at=sent_at,
            )
        )
    db_session.commit()
    return conversation


def add_whatsapp_message(db_session, tenant_id, *, created_at, text, external_account_id="edi-crm-whatsapp"):
    message = Communication(
        tenant_id=tenant_id,
        channel="whatsapp",
        direction="outbound",
        provider="whatsapp-service",
        external_account_id=external_account_id,
        whatsapp_chat_id="326472368@lid",
        whatsapp_identity_key="326472368@lid",
        message=text,
        created_at=created_at,
    )
    db_session.add(message)
    db_session.commit()
    return message


def test_whatsapp_message_between_two_emails_appears_as_inline_block(db_session):
    tenant = create_tenant(db_session, booking_id="B-inline-block")
    first_email_at = datetime(2026, 7, 7, 17, 24, tzinfo=timezone.utc)
    second_email_at = datetime(2026, 7, 10, 14, 21, tzinfo=timezone.utc)
    add_email_conversation(db_session, tenant.id, subject="CRM test", message_times=[first_email_at, second_email_at])

    # Falls strictly between the thread's two email messages.
    between_at = first_email_at + timedelta(days=1)
    add_whatsapp_message(db_session, tenant.id, created_at=between_at, text="between the emails")

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    email_items = [item for item in timeline.items if item.type == "email_thread"]
    assert len(email_items) == 1

    block_texts = [message.message for block in email_items[0].whatsapp_blocks for message in block.messages]
    assert "between the emails" in block_texts


def test_whatsapp_message_after_last_email_is_not_forced_into_thread_but_still_shown(db_session):
    """Messages after a thread's last email are not inline blocks (they're a standalone
    WhatsApp Group per the existing, intentionally-unchanged grouping behavior), but they
    must still appear somewhere in the timeline rather than being dropped."""
    tenant = create_tenant(db_session, booking_id="B-after-thread")
    first_email_at = datetime(2026, 7, 7, 17, 24, tzinfo=timezone.utc)
    second_email_at = datetime(2026, 7, 10, 14, 21, tzinfo=timezone.utc)
    add_email_conversation(db_session, tenant.id, subject="CRM test", message_times=[first_email_at, second_email_at])

    after_at = second_email_at + timedelta(hours=4)
    add_whatsapp_message(db_session, tenant.id, created_at=after_at, text="after the last email")

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    email_items = [item for item in timeline.items if item.type == "email_thread"]
    group_items = [item for item in timeline.items if item.type == "whatsapp_group"]

    block_texts = [message.message for block in email_items[0].whatsapp_blocks for message in block.messages]
    group_texts = [message.message for group in group_items for message in group.messages]

    assert "after the last email" not in block_texts
    assert "after the last email" in group_texts


def test_whatsapp_message_between_emails_is_duplicated_in_both_block_and_group(db_session):
    """Per product decision: a WhatsApp message inside a thread's own date range should be
    added to that thread's inline blocks IN ADDITION TO wherever the pre-existing group-bucketing
    logic already places it -- duplication between the two is expected and acceptable."""
    tenant = create_tenant(db_session, booking_id="B-duplicate-ok")
    first_email_at = datetime(2026, 7, 7, 17, 24, tzinfo=timezone.utc)
    second_email_at = datetime(2026, 7, 10, 14, 21, tzinfo=timezone.utc)
    add_email_conversation(db_session, tenant.id, subject="CRM test", message_times=[first_email_at, second_email_at])

    between_at = first_email_at + timedelta(days=1)
    add_whatsapp_message(db_session, tenant.id, created_at=between_at, text="between the emails")

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    email_items = [item for item in timeline.items if item.type == "email_thread"]
    group_items = [item for item in timeline.items if item.type == "whatsapp_group"]

    block_texts = [message.message for block in email_items[0].whatsapp_blocks for message in block.messages]
    group_texts = [message.message for group in group_items for message in group.messages]

    assert "between the emails" in block_texts
    assert "between the emails" in group_texts
