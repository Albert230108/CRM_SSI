from datetime import datetime, timezone
import re

from sqlalchemy.orm import Session

from app.core.phone_normalization import phone_match_candidates
from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_approval_request import AiAutoDraftApprovalRequest
from app.models.tenant import Tenant
from app.models.user import User
from app.services import ai_auto_draft_service

_CODE_PATTERN = re.compile(r"\b(YES|NO)[-\s]?(\d+)\b", re.IGNORECASE)

PENDING_STATUSES = ("pending", "needs_review")


def _match_admin_user(db: Session, sender_phone: str | None) -> User | None:
    sender_candidates = set(phone_match_candidates(sender_phone))
    if not sender_candidates:
        return None

    recipients = (
        db.query(User)
        .filter(User.whatsapp_notifications_enabled.is_(True), User.is_active.is_(True), User.phone.isnot(None))
        .all()
    )
    for user in recipients:
        if sender_candidates & set(phone_match_candidates(user.phone)):
            return user
    return None


def _already_handled_reply(db: Session, draft: AiAutoDraft) -> str:
    resolver_request = (
        db.query(AiAutoDraftApprovalRequest)
        .filter(
            AiAutoDraftApprovalRequest.ai_auto_draft_id == draft.id,
            AiAutoDraftApprovalRequest.responded_at.isnot(None),
        )
        .order_by(AiAutoDraftApprovalRequest.responded_at.asc())
        .first()
    )
    if resolver_request is None:
        return f"This draft is no longer pending (status: {draft.status})."

    resolver = db.query(User).filter(User.id == resolver_request.user_id).first()
    resolver_name = resolver.full_name if resolver is not None and resolver.full_name else "another user"
    responded_at = resolver_request.responded_at
    return (
        f"Already handled by {resolver_name}: replied {resolver_request.response} "
        f"at {responded_at.strftime('%Y-%m-%d %H:%M UTC')}."
    )


def try_handle_admin_reply(
    db: Session, *, external_account_id: str | None, sender_phone: str | None, text: str | None
) -> str | None:
    """Checks whether an inbound WhatsApp message is a staff member replying to an AI-draft
    approval ping (e.g. "YES-482"), and if so, acts on it and returns the confirmation text
    to send back.

    Returns None for anything that isn't a recognized admin approval reply - the WhatsApp
    account doesn't match the configured notification account, the sender isn't an opted-in
    user, or the text has no YES/NO-<id> code - so the caller can fall through to normal
    tenant-message routing unchanged.
    """
    settings = db.query(AdminSettings).first()
    notification_account_id = settings.notification_whatsapp_external_account_id if settings is not None else None
    if not notification_account_id or external_account_id != notification_account_id:
        return None

    user = _match_admin_user(db, sender_phone)
    if user is None:
        return None

    match = _CODE_PATTERN.search(text or "")
    if not match:
        return None

    decision = match.group(1).upper()
    draft_id = int(match.group(2))

    approval_request = (
        db.query(AiAutoDraftApprovalRequest)
        .filter(AiAutoDraftApprovalRequest.ai_auto_draft_id == draft_id, AiAutoDraftApprovalRequest.user_id == user.id)
        .first()
    )
    if approval_request is None:
        return f"No pending draft notification found for that code ({decision}-{draft_id})."

    draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).first()
    if draft is None:
        return "That draft no longer exists."

    if draft.status not in PENDING_STATUSES:
        return _already_handled_reply(db, draft)

    if decision == "YES":
        sent = ai_auto_draft_service.send_scheduled_draft(db, draft)
        if not sent:
            # Left unanswered on purpose: nothing was persisted for this attempt, and leaving
            # the approval_request row without a response lets the same or another admin retry.
            return "⚠️ Failed to send — check the draft in the CRM."
        approval_request.responded_at = datetime.now(timezone.utc)
        approval_request.response = decision
        db.commit()
        tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
        tenant_name = tenant.name if tenant is not None else "the tenant"
        return f"✅ Sent to {tenant_name}."

    draft.status = "dismissed"
    draft.scheduled_send_at = None
    approval_request.responded_at = datetime.now(timezone.utc)
    approval_request.response = decision
    db.commit()
    return "🗑️ Draft dismissed."
