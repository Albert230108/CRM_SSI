from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import re

from sqlalchemy.orm import Session

from app.core.phone_normalization import phone_match_candidates
from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_approval_request import AiAutoDraftApprovalRequest
from app.models.tenant import Tenant
from app.models.user import User
from app.services import ai_auto_draft_service

logger = logging.getLogger(__name__)

_CODE_PATTERN = re.compile(r"\b(YES|NO)[-\s]?(\d+)\b", re.IGNORECASE)
# A reply that is nothing but a yes/no, which carries no draft id of its own.
_BARE_PATTERN = re.compile(r"^\s*(yes|no|y|n)\s*[.!]*\s*$", re.IGNORECASE)

PENDING_STATUSES = ("pending", "needs_review")


@dataclass(frozen=True)
class AdminReplyOutcome:
    """The confirmation to send back, addressed to the replying user's stored phone number.

    The confirmation deliberately goes to the phone rather than back to the raw inbound sender:
    an @lid sender id is not a reliable send target, while the phone is the same address the
    original notification was successfully delivered to.
    """

    reply_text: str
    reply_to_phone: str | None


def _match_admin_user(
    db: Session, sender_phone: str | None, sender_identities: Sequence[str | None] = ()
) -> User | None:
    """Identifies which opted-in staff member sent an inbound message.

    Matches on the sender's WhatsApp identity first: a staff member on an @lid-addressed
    account replies from that @lid, which their stored phone number can never match. Falls
    back to phone matching for ordinary @c.us senders and users whose @lid is not known yet.

    Deliberately takes every identifier that could name the *sender* (the raw sender field and
    the raw chat id) rather than the canonical identity: for an inbound message from an @lid
    the canonical id resolves to this CRM's own number, since it falls back to the recipient's
    phone when the sender has none.
    """
    recipients = (
        db.query(User)
        .filter(User.whatsapp_notifications_enabled.is_(True), User.is_active.is_(True))
        .all()
    )

    identity_candidates = {
        value.strip().lower() for value in sender_identities if value and value.strip()
    }
    if identity_candidates:
        for user in recipients:
            stored = (user.whatsapp_identity_key or "").strip().lower()
            if stored and stored in identity_candidates:
                return user

    sender_candidates = set(phone_match_candidates(sender_phone))
    for value in identity_candidates:
        sender_candidates |= set(phone_match_candidates(value))
    if not sender_candidates:
        return None
    for user in recipients:
        if sender_candidates & set(phone_match_candidates(user.phone)):
            return user
    return None


def _outstanding_requests_for_user(
    db: Session, user_id: int
) -> list[tuple[AiAutoDraftApprovalRequest, str]]:
    """The drafts this user was notified about that are still awaiting a decision.

    Excludes drafts that have moved on (sent, dismissed, or superseded by a newer draft after
    a fresh inbound message), since those can no longer be acted on.
    """
    rows = (
        db.query(AiAutoDraftApprovalRequest, Tenant.name)
        .join(AiAutoDraft, AiAutoDraft.id == AiAutoDraftApprovalRequest.ai_auto_draft_id)
        .outerjoin(Tenant, Tenant.id == AiAutoDraft.tenant_id)
        .filter(
            AiAutoDraftApprovalRequest.user_id == user_id,
            AiAutoDraftApprovalRequest.responded_at.is_(None),
            AiAutoDraft.status.in_(PENDING_STATUSES),
        )
        .order_by(AiAutoDraftApprovalRequest.ai_auto_draft_id.asc())
        .all()
    )
    return [(request, tenant_name or "Unknown tenant") for request, tenant_name in rows]


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
    db: Session,
    *,
    external_account_id: str | None,
    sender_phone: str | None,
    text: str | None,
    sender_identities: Sequence[str | None] = (),
) -> AdminReplyOutcome | None:
    """Checks whether an inbound WhatsApp message is a staff member replying to an AI-draft
    approval ping (e.g. "YES-482"), and if so, acts on it and returns the confirmation to
    send back.

    Returns None for anything that isn't a recognized staff approval reply - the WhatsApp
    account doesn't match the configured notification account, the sender isn't an opted-in
    user, or the text has no YES/NO decision - so the caller can fall through to normal
    tenant-message routing unchanged.
    """
    settings = db.query(AdminSettings).first()
    notification_account_id = settings.notification_whatsapp_external_account_id if settings is not None else None
    if not notification_account_id or external_account_id != notification_account_id:
        return None

    # Everything below is logged at warning level on purpose: this account carries only staff
    # alert traffic, so the volume is low, and a staff approval that gets dropped must never be
    # invisible. (The app configures no logging, so the root logger emits warning and above.)
    logger.warning(
        "Staff draft reply received account=%s sender_phone=%s sender_identities=%s text=%r",
        external_account_id,
        sender_phone,
        list(sender_identities),
        (text or "")[:200],
    )

    user = _match_admin_user(db, sender_phone, sender_identities)
    if user is None:
        logger.warning(
            "Staff draft reply ignored: sender not an opted-in user sender_phone=%s sender_identities=%s",
            sender_phone,
            list(sender_identities),
        )
        return None

    reply_to_phone = (user.phone or "").strip() or None

    def outcome(reply_text: str) -> AdminReplyOutcome:
        return AdminReplyOutcome(reply_text=reply_text, reply_to_phone=reply_to_phone)

    match = _CODE_PATTERN.search(text or "")
    bare_match = None if match else _BARE_PATTERN.match(text or "")
    if not match and not bare_match:
        logger.warning(
            "Staff draft reply ignored: no YES/NO decision found user_id=%s text=%r",
            user.id,
            (text or "")[:200],
        )
        return None

    if match:
        decision = match.group(1).upper()
        draft_id = int(match.group(2))
    else:
        # A bare "yes"/"no" is the natural thing to type, so resolve it against whatever this
        # user still has outstanding rather than ignoring it. Only safe when exactly one draft
        # is waiting; otherwise the reply is genuinely ambiguous and must be disambiguated.
        decision = "YES" if bare_match.group(1).lower().startswith("y") else "NO"
        outstanding = _outstanding_requests_for_user(db, user.id)
        if not outstanding:
            return outcome("You have no AI drafts waiting for approval right now.")
        if len(outstanding) > 1:
            listed = "\n".join(
                f"- {decision}-{request.ai_auto_draft_id} ({tenant_name})"
                for request, tenant_name in outstanding
            )
            return outcome(
                f"You have {len(outstanding)} drafts waiting, so \"{decision.lower()}\" is ambiguous.\n"
                f"Reply with the code for the one you mean:\n{listed}"
            )
        draft_id = outstanding[0][0].ai_auto_draft_id

    approval_request = (
        db.query(AiAutoDraftApprovalRequest)
        .filter(AiAutoDraftApprovalRequest.ai_auto_draft_id == draft_id, AiAutoDraftApprovalRequest.user_id == user.id)
        .first()
    )
    if approval_request is None:
        return outcome(f"No pending draft notification found for that code ({decision}-{draft_id}).")

    draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).first()
    if draft is None:
        return outcome("That draft no longer exists.")

    if draft.status not in PENDING_STATUSES:
        return outcome(_already_handled_reply(db, draft))

    if decision == "YES":
        sent = ai_auto_draft_service.send_scheduled_draft(db, draft)
        if not sent:
            # Left unanswered on purpose: nothing was persisted for this attempt, and leaving
            # the approval_request row without a response lets the same or another admin retry.
            return outcome("⚠️ Failed to send — check the draft in the CRM.")
        approval_request.responded_at = datetime.now(timezone.utc)
        approval_request.response = decision
        db.commit()
        tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
        tenant_name = tenant.name if tenant is not None else "the tenant"
        return outcome(f"✅ Sent to {tenant_name}.")

    draft.status = "dismissed"
    draft.scheduled_send_at = None
    approval_request.responded_at = datetime.now(timezone.utc)
    approval_request.response = decision
    db.commit()
    return outcome("🗑️ Draft dismissed.")
