from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio
import logging
import re

from sqlalchemy.orm import Session

from app.core.phone_normalization import phone_match_candidates
from app.models.action_item import ActionItem
from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_approval_request import AiAutoDraftApprovalRequest
from app.models.memory_suggestion import (
    KIND_ACTION_ITEM_COMPLETE,
    KIND_ACTION_ITEM_DELETE,
    KIND_ACTION_ITEM_MODIFY,
    MemorySuggestion,
    STATUS_PENDING,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services import action_item_service
from app.services import ai_auto_draft_service
from app.services import ai_draft_notification_service
from app.services import memory_redo_service
from app.services import memory_suggestion_service
from app.services import redo_request_log_service
from app.services import whatsapp_action_digest_service
from app.services.whatsapp_client import WhatsAppBridgeError

logger = logging.getLogger(__name__)

_CODE_PATTERN = re.compile(r"\b(YES|NO)[-\s]?(\d+)\b", re.IGNORECASE)
# A reply that is nothing but a yes/no, which carries no draft id of its own.
_BARE_PATTERN = re.compile(r"^\s*(yes|no|y|n)\s*[.!]*\s*$", re.IGNORECASE)
# REDO carries free-text instructions after the code, so it's matched against the whole
# message rather than as a \b-delimited token like YES/NO. What/why extraction from that free
# text happens separately in _extract_what_why, since staff type it by hand on WhatsApp and
# routinely mix up order, skip "why", or vary casing.
_REDO_PATTERN = re.compile(r"^\s*REDO[-\s]?(\d+)\s*[:\-]?\s*(.*)$", re.IGNORECASE | re.DOTALL)
_DOMAIN_CODE_PATTERN = re.compile(r"^\s*(DRAFT|ACTION)[-\s]?(YES|NO)[-\s]?(\d+)\b", re.IGNORECASE)
_WHAT_LABEL = "what:"
_WHY_LABEL = "why:"


def _extract_what_why(text: str) -> tuple[str, str | None]:
    """Forgiving, order-independent extraction of what:/why: from human-typed WhatsApp text.

    Staff will mix up order, skip either label, or vary casing, so this handles each
    combination explicitly rather than assuming a fixed sequence:
      - neither label present -> the whole text is "what" (matches the pre-existing plain
        "REDO-{id} <instructions>" format, so that still works unchanged)
      - only "what:" present -> everything after it is "what"
      - only "why:" present -> everything before it is the implicit "what", everything after is "why"
      - both present, "what:" first -> text between the labels is "what", text after "why:" is "why"
      - both present, "why:" first -> text between the labels is "why", text after "what:" is "what"
    """
    lower = text.lower()
    what_idx = lower.find(_WHAT_LABEL)
    why_idx = lower.find(_WHY_LABEL)

    if what_idx == -1 and why_idx == -1:
        return text.strip(), None

    if what_idx != -1 and why_idx == -1:
        return text[what_idx + len(_WHAT_LABEL) :].strip(), None

    if what_idx == -1 and why_idx != -1:
        what_text = text[:why_idx].strip()
        why_text = text[why_idx + len(_WHY_LABEL) :].strip() or None
        return what_text, why_text

    if what_idx < why_idx:
        what_text = text[what_idx + len(_WHAT_LABEL) : why_idx].strip()
        why_text = text[why_idx + len(_WHY_LABEL) :].strip() or None
    else:
        why_text = text[why_idx + len(_WHY_LABEL) : what_idx].strip() or None
        what_text = text[what_idx + len(_WHAT_LABEL) :].strip()
    return what_text, why_text


def _combine_what_why(what: str, why: str | None) -> str:
    combined = f"What: {what}"
    if why:
        combined += f"\nWhy: {why}"
    return combined

PENDING_STATUSES = ("pending", "needs_review")


@dataclass(frozen=True)
class AdminReplyOutcome:
    """The confirmation to send back, addressed to the replying user's stored phone number.

    The confirmation deliberately goes to the phone rather than back to the raw inbound sender:
    an @lid sender id is not a reliable send target, while the phone is the same address the
    original notification was successfully delivered to.
    """

    # None means the caller already sent everything the requester needs to see (e.g. a REDO
    # whose acknowledgement and redone-draft broadcast were already sent directly) - the webhook
    # must not send a further confirmation in that case.
    reply_text: str | None
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


def _handle_redo_reply(
    db: Session,
    *,
    user: User,
    external_account_id: str,
    redo_match: re.Match[str],
    outcome,
) -> AdminReplyOutcome:
    """Handles a "REDO-{id} <instructions>" reply: regenerates the draft in place and
    re-broadcasts it to every opted-in admin under the same code.
    """
    draft_id = int(redo_match.group(1))
    what, why = _extract_what_why(redo_match.group(2).strip())
    if not what:
        return outcome(f"Please include what to change, e.g. REDO-{draft_id} make it shorter.")
    instructions = _combine_what_why(what, why)

    approval_request = (
        db.query(AiAutoDraftApprovalRequest)
        .filter(AiAutoDraftApprovalRequest.ai_auto_draft_id == draft_id, AiAutoDraftApprovalRequest.user_id == user.id)
        .first()
    )
    if approval_request is None:
        return outcome(f"No pending draft notification found for that code (REDO-{draft_id}).")

    draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).first()
    if draft is None:
        return outcome("That draft no longer exists.")

    if draft.status not in PENDING_STATUSES:
        return outcome(_already_handled_reply(db, draft))

    # Regenerating runs the full planner/drafter/checker loop, which can take several seconds -
    # acknowledge the request up front so it arrives before the redone draft, not after it.
    phone = (user.phone or "").strip()
    if phone:
        try:
            asyncio.run(
                ai_draft_notification_service.send_system_whatsapp_message(
                    to=phone, message="🔄 Redoing draft with your notes…", external_account_id=external_account_id
                )
            )
        except WhatsAppBridgeError:
            logger.exception("Failed to send redo acknowledgement user_id=%s draft_id=%s", user.id, draft_id)

    regenerated = ai_auto_draft_service.regenerate_draft_via_planner(db, draft, instructions)
    if regenerated is None:
        # Logged even on failure - the redo log is an accessible record of every attempt, not
        # just the ones that succeeded.
        redo_request_log_service.log_redo_request(
            db, ai_auto_draft_id=draft_id, tenant_id=draft.tenant_id, channel="whatsapp", what=what, why=why, requested_by_user_id=user.id
        )
        db.commit()
        return outcome(
            f"⚠️ Redo failed — planner produced no draft. Try again or reply NO-{draft_id} to dismiss."
        )

    log_entry = redo_request_log_service.log_redo_request(
        db, ai_auto_draft_id=draft_id, tenant_id=regenerated.tenant_id, channel="whatsapp", what=what, why=why, requested_by_user_id=user.id
    )
    db.commit()
    try:
        memory_redo_service.propose_updates_from_redo(db, regenerated, what, why, redo_log_id=log_entry.id)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Memory redo suggestion generation failed draft_id=%s", draft_id)
    ai_draft_notification_service.notify_admins_of_redraft(db, regenerated)
    # The acknowledgement above already told the requester a redo is in progress, and the
    # broadcast just sent them the regenerated draft under the same code - nothing more to say.
    return AdminReplyOutcome(reply_text=None, reply_to_phone=None)


def _action_item_suggestion_for_id(db: Session, suggestion_id: int) -> MemorySuggestion | None:
    return (
        db.query(MemorySuggestion)
        .filter(
            MemorySuggestion.id == suggestion_id,
            MemorySuggestion.status == STATUS_PENDING,
            MemorySuggestion.kind.in_((KIND_ACTION_ITEM_MODIFY, KIND_ACTION_ITEM_DELETE, KIND_ACTION_ITEM_COMPLETE)),
        )
        .first()
    )


def _action_item_suggestion_rows(db: Session, suggestions: list[MemorySuggestion]) -> list[tuple[MemorySuggestion, ActionItem | None, str]]:
    rows: list[tuple[MemorySuggestion, ActionItem | None, str]] = []
    for suggestion in suggestions:
        item = db.query(ActionItem).filter(ActionItem.id == suggestion.target_id).first() if suggestion.target_id is not None else None
        tenant = db.query(Tenant).filter(Tenant.id == suggestion.tenant_id).first() if suggestion.tenant_id is not None else None
        rows.append((suggestion, item, tenant.name if tenant is not None else "Unknown tenant"))
    return rows


def _action_item_tenant_names(db: Session, items: list[ActionItem]) -> dict[int, str]:
    tenant_ids = {item.tenant_id for item in items}
    if not tenant_ids:
        return {}
    tenants = db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).all()
    return {tenant.id: tenant.name for tenant in tenants}


def _handle_action_item_suggestion_reply(
    db: Session,
    *,
    user: User,
    suggestion: MemorySuggestion,
    decision: str,
    outcome,
) -> AdminReplyOutcome:
    if decision == "YES":
        result = memory_suggestion_service.approve(db, suggestion, reviewer_id=user.id)
        db.commit()
        if result.applied:
            return outcome(f"✅ Approved action-item suggestion #{suggestion.id}: {result.message}")
        return outcome(f"⚠️ Action-item suggestion #{suggestion.id} could not be applied: {result.message}")

    memory_suggestion_service.reject(db, suggestion, reviewer_id=user.id)
    db.commit()
    return outcome(f"🗑️ Rejected action-item suggestion #{suggestion.id}.")


def _format_action_item_disambiguation(draft_id: int) -> str:
    return (
        f"That code matches both a draft approval and a pending action-item suggestion. "
        f"Reply DRAFT-YES-{draft_id} / DRAFT-NO-{draft_id} for the draft, or "
        f"ACTION-YES-{draft_id} / ACTION-NO-{draft_id} for the action item."
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

    command = whatsapp_action_digest_service.resolve_command(text or "")
    if command == "today":
        items = action_item_service.list_open_today_or_overdue(db)
        tenant_names = _action_item_tenant_names(db, items)
        return outcome(
            whatsapp_action_digest_service.format_open_actions_message(
                items, tenant_names=tenant_names, heading="📋 Open actions (today & overdue)"
            )
        )
    if command == "upcoming":
        items = action_item_service.list_open_upcoming(db)
        tenant_names = _action_item_tenant_names(db, items)
        return outcome(
            whatsapp_action_digest_service.format_open_actions_message(
                items, tenant_names=tenant_names, heading="📋 Open actions (upcoming 7 days)"
            )
        )
    if command == "pending":
        suggestions = memory_suggestion_service.list_pending_action_item_suggestions(db)
        return outcome(
            whatsapp_action_digest_service.format_pending_suggestions_message(_action_item_suggestion_rows(db, suggestions))
        )
    if command == "help":
        return outcome(whatsapp_action_digest_service.format_help_message())

    redo_match = _REDO_PATTERN.match(text or "")
    if redo_match:
        return _handle_redo_reply(
            db, user=user, external_account_id=notification_account_id, redo_match=redo_match, outcome=outcome
        )

    domain_match = _DOMAIN_CODE_PATTERN.match(text or "")
    if domain_match:
        domain = domain_match.group(1).upper()
        decision = domain_match.group(2).upper()
        draft_id = int(domain_match.group(3))
        if domain == "ACTION":
            suggestion = _action_item_suggestion_for_id(db, draft_id)
            if suggestion is None:
                return outcome(f"No pending action-item suggestion found for that code ({decision}-{draft_id}).")
            return _handle_action_item_suggestion_reply(db, user=user, suggestion=suggestion, decision=decision, outcome=outcome)

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

        reason = f"{decision.title()} via WhatsApp by {user.full_name or user.email}"
        if decision == "YES":
            sent = ai_auto_draft_service.send_scheduled_draft(db, draft, resolution_source="human_whatsapp", reason=reason)
            if not sent:
                return outcome("⚠️ Failed to send — check the draft in the CRM.")
            approval_request.responded_at = datetime.now(timezone.utc)
            approval_request.response = decision
            db.commit()
            tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
            tenant_name = tenant.name if tenant is not None else "the tenant"
            return outcome(f"✅ Sent to {tenant_name}.")

        draft.status = "dismissed"
        draft.scheduled_send_at = None
        draft.resolution_source = "human_whatsapp"
        draft.resolution_reason = reason
        approval_request.responded_at = datetime.now(timezone.utc)
        approval_request.response = decision
        db.commit()
        return outcome("🗑️ Draft dismissed.")

    match = _CODE_PATTERN.search(text or "")
    bare_match = None if match else _BARE_PATTERN.match(text or "")
    if not match and not bare_match:
        logger.warning(
            "Staff draft reply ignored: no YES/NO decision found user_id=%s text=%r",
            user.id,
            (text or "")[:200],
        )
        return None

    typed_reason: str | None = None
    if match:
        decision = match.group(1).upper()
        draft_id = int(match.group(2))
        typed_reason = text[match.end() :].strip().lstrip(":-").strip() or None if text else None
    else:
        decision = "YES" if bare_match.group(1).lower().startswith("y") else "NO"
        outstanding = _outstanding_requests_for_user(db, user.id)
        if not outstanding:
            return outcome("You have no AI drafts waiting for approval right now.")
        if decision == "YES" and len(outstanding) == 1:
            draft_id = outstanding[0][0].ai_auto_draft_id
            return outcome(f"Please reply YES-{draft_id} to send that draft.")
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
    action_item_suggestion = _action_item_suggestion_for_id(db, draft_id)
    if approval_request is not None and action_item_suggestion is not None:
        return outcome(_format_action_item_disambiguation(draft_id))
    if action_item_suggestion is not None:
        return _handle_action_item_suggestion_reply(
            db, user=user, suggestion=action_item_suggestion, decision=decision, outcome=outcome
        )
    if approval_request is None:
        return outcome(f"No pending draft or action-item notification found for that code ({decision}-{draft_id}).")

    draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).first()
    if draft is None:
        return outcome("That draft no longer exists.")

    if draft.status not in PENDING_STATUSES:
        return outcome(_already_handled_reply(db, draft))

    reason = typed_reason or f"{decision.title()} via WhatsApp by {user.full_name or user.email}"

    if decision == "YES":
        sent = ai_auto_draft_service.send_scheduled_draft(db, draft, resolution_source="human_whatsapp", reason=reason)
        if not sent:
            return outcome("⚠️ Failed to send — check the draft in the CRM.")
        approval_request.responded_at = datetime.now(timezone.utc)
        approval_request.response = decision
        db.commit()
        tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
        tenant_name = tenant.name if tenant is not None else "the tenant"
        return outcome(f"✅ Sent to {tenant_name}.")

    draft.status = "dismissed"
    draft.scheduled_send_at = None
    draft.resolution_source = "human_whatsapp"
    draft.resolution_reason = reason
    approval_request.responded_at = datetime.now(timezone.utc)
    approval_request.response = decision
    db.commit()
    return outcome("🗑️ Draft dismissed.")
