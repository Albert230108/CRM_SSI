from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount

PROVIDER_GMAIL = "gmail"


def persist_gmail_outbound_message(
    db: Session,
    *,
    tenant_id: int,
    conversation: Conversation,
    account: GmailAccount,
    to_email: str,
    subject: str,
    message: str,
    gmail_result: dict[str, Any],
    ai_generated: bool = False,
) -> Communication:
    """Persist a Gmail message the CRM just sent (manually or via AI auto-send).

    Writes both the thread-scoped ConversationMessage (for the email timeline) and a
    Communication row (for the tenant's cross-channel timeline) - the same dual-write the
    manual send endpoint already relied on inline, now shared with the auto-send scheduler.
    """
    now = datetime.now(timezone.utc)
    provider_message_id = gmail_result.get("id")
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider=PROVIDER_GMAIL,
            provider_message_id=provider_message_id or "",
            direction="outbound",
            sender_email=account.email_address,
            recipient_email=to_email,
            subject=subject,
            body=message,
            sent_at=now,
            raw_payload={"gmail": gmail_result},
        )
    )
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
        ai_generated=ai_generated,
    )
    db.add(communication)
    db.commit()
    db.refresh(communication)
    return communication
