from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant_conversation_link import TenantConversationLink

# Statuses of an auto-draft that is still awaiting an outcome (surfaced on the Pending AI Drafts
# page or still being produced). Hiding a thread must clear exactly these, leaving terminal
# states (sent / dismissed / superseded / used_as_manual_seed) untouched for the audit trail.
_ACTIVE_DRAFT_STATUSES = ("generating", "pending", "pending_auto_send", "needs_review")


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


def dismiss_ai_artifacts_for_hidden_link(db: Session, tenant_id: int, conversation_id: int) -> None:
    """Clear the pending auto-draft artifacts tied to a thread a tenant just hid.

    Hiding is a per-tenant reversible flag (TenantConversationLink.is_visible=False), but a hidden
    thread must behave as if it were not linked to the tenant at all. New drafts are already gated
    on visibility (ai_auto_draft_service.generate_draft_for_trigger), so this only cleans up what
    was created before the thread was hidden: any in-flight/pending draft is dismissed and the
    debounce trigger is removed so the scheduler will not regenerate. Terminal drafts are left
    untouched. Does not commit - the caller owns the surrounding transaction.
    """
    db.query(AiAutoDraft).filter(
        AiAutoDraft.tenant_id == tenant_id,
        AiAutoDraft.channel == "email",
        AiAutoDraft.email_thread_id == conversation_id,
        AiAutoDraft.status.in_(_ACTIVE_DRAFT_STATUSES),
    ).update({"status": "dismissed"}, synchronize_session=False)

    db.query(AiAutoDraftTrigger).filter(
        AiAutoDraftTrigger.tenant_id == tenant_id,
        AiAutoDraftTrigger.channel == "email",
        AiAutoDraftTrigger.email_thread_id == conversation_id,
    ).delete(synchronize_session=False)


def visible_tenant_for_conversation(
    db: Session, conversation_id: int, prefer_tenant_id: int | None = None
) -> int | None:
    """Return the tenant a shared thread is currently *active* for (visible + not unlinked).

    A conversation can be linked to several tenants that share an email address; only some of them
    keep it visible. Prefer `prefer_tenant_id` (the draft/notification's stored tenant) when it
    still has a visible link, so routing stays stable; otherwise fall back to any tenant that does,
    and finally to `prefer_tenant_id` itself when none qualifies (nothing better to point at).
    """
    visible_tenant_ids = [
        row[0]
        for row in db.query(TenantConversationLink.tenant_id)
        .filter(
            TenantConversationLink.conversation_id == conversation_id,
            TenantConversationLink.unlinked_at.is_(None),
            TenantConversationLink.is_visible.is_(True),
        )
        .order_by(TenantConversationLink.tenant_id)
        .all()
    ]
    if prefer_tenant_id is not None and prefer_tenant_id in visible_tenant_ids:
        return prefer_tenant_id
    if visible_tenant_ids:
        return visible_tenant_ids[0]
    return prefer_tenant_id
