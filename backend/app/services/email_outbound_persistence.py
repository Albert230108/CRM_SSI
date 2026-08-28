from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.services import action_writer_trigger_service, tenant_brain_trigger_service
from app.services.attachment_service import link_attachments

PROVIDER_GMAIL = "gmail"


def is_own_mailbox_address(db: Session, email: str | None) -> bool:
    normalized = (email or "").strip().lower()
    if not normalized:
        return False
    return (
        db.query(GmailAccount.id)
        .filter(func.lower(GmailAccount.email_address) == normalized)
        .first()
        is not None
    )


def persist_gmail_outbound_message(
    db: Session,
    *,
    tenant_id: int,
    conversation: Conversation,
    account: GmailAccount,
    to_email: str,
    cc: str | None = None,
    subject: str,
    message: str,
    gmail_result: dict[str, Any],
    body_html: str | None = None,
    ai_generated: bool = False,
    attachment_ids: list[int] | None = None,
) -> Communication:
    """Persist a Gmail message the CRM just sent (manually or via AI auto-send).

    Writes both the thread-scoped ConversationMessage (for the email timeline) and a
    Communication row (for the tenant's cross-channel timeline) - the same dual-write the
    manual send endpoint already relied on inline, now shared with the auto-send scheduler.
    """
    now = datetime.now(timezone.utc)
    provider_message_id = gmail_result.get("id")
    conversation_message = ConversationMessage(
        conversation_id=conversation.id,
        provider=PROVIDER_GMAIL,
        provider_message_id=provider_message_id or "",
        direction="outbound",
        sender_email=account.email_address,
        recipient_email=to_email,
        subject=subject,
        cc=cc,
        body=message,
        sent_at=now,
        raw_payload={"gmail": gmail_result, "body_text": message, "body_html": body_html, "cc": cc},
    )
    db.add(conversation_message)
    db.commit()

    communication = Communication(
        tenant_id=tenant_id,
        channel="email",
        direction="outbound",
        provider=PROVIDER_GMAIL,
        external_account_id=account.email_address,
        subject=subject,
        message=message,
        created_at=now,
        cc=cc,
        ai_generated=ai_generated,
    )
    db.add(communication)
    tenant_brain_trigger_service.register_message_trigger(
        db, tenant_id=tenant_id, channel="email", direction="outbound", email_thread_id=conversation.id
    )
    action_writer_trigger_service.register_message_trigger(
        db, tenant_id=tenant_id, channel="email", direction="outbound", email_thread_id=conversation.id
    )
    db.commit()
    db.refresh(communication)

    # Link to both sides of the dual write: the ConversationMessage drives the email
    # thread view, the Communication drives the cross-channel tenant timeline.
    if attachment_ids:
        link_attachments(db, attachment_ids=attachment_ids, conversation_message_id=conversation_message.id)
        link_attachments(db, attachment_ids=attachment_ids, communication_id=communication.id)

    return communication
