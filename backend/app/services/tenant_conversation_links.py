from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant_conversation_link import TenantConversationLink


def remove_conversations_for_matched_email(db: Session, tenant_id: int, email: str) -> tuple[int, int]:
    """Detach every conversation this tenant's link to `email` matched, since the tenant no
    longer owns that address. Matched case-insensitively since matched_email is recorded from
    lowercased header addresses (see gmail_integration._find_tenants_for_message) while the
    caller's email may come from Beds24/manual entry with its original casing. A conversation
    also linked to a *different* tenant is left alone (only this tenant's link is removed) --
    deleting it would erase that other tenant's history too. Returns
    (conversations_deleted, conversations_only_unlinked).
    """
    now = datetime.now(timezone.utc)
    conversation_links = (
        db.query(TenantConversationLink)
        .filter(
            TenantConversationLink.tenant_id == tenant_id,
            func.lower(TenantConversationLink.matched_email) == email.lower(),
            TenantConversationLink.unlinked_at.is_(None),
        )
        .all()
    )

    deleted = 0
    unlinked_shared = 0
    for conversation_link in conversation_links:
        conversation_id = conversation_link.conversation_id
        other_tenant_has_active_link = (
            db.query(TenantConversationLink)
            .filter(
                TenantConversationLink.conversation_id == conversation_id,
                TenantConversationLink.tenant_id != tenant_id,
                TenantConversationLink.unlinked_at.is_(None),
            )
            .first()
            is not None
        )
        if other_tenant_has_active_link:
            conversation_link.unlinked_at = now
            unlinked_shared += 1
            continue

        db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).delete(synchronize_session=False)
        db.query(TenantConversationLink).filter(TenantConversationLink.conversation_id == conversation_id).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.id == conversation_id).delete(synchronize_session=False)
        deleted += 1

    return deleted, unlinked_shared
