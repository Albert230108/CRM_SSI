import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.ai_agent_run import STATUS_NEEDS_REVIEW
from app.models.ai_reply_template import AiReplyTemplate
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services import ai_agent_orchestrator, ai_reply_service
from app.services.email_outbound_persistence import is_own_mailbox_address, persist_gmail_outbound_message
from app.services.gmail_client import build_gmail_credentials, send_gmail_reply
from app.services.tenant_phone_aliases import get_tenant_primary_phone_raw
from app.services.whatsapp_client import send_whatsapp_message
from app.services.whatsapp_outbound_persistence import persist_whatsapp_outbound_communication

logger = logging.getLogger(__name__)


def _auto_send_delay_seconds(db: Session) -> int:
    settings = db.query(AdminSettings).first()
    return settings.ai_auto_send_delay_seconds if settings is not None else 300


def _build_quoted_context(original_text: str | None) -> str | None:
    """The inbound message a draft answers, framed for human display (e.g. in the WhatsApp
    approval ping or the AI Drafts page) - never appended to generated_text, since that column
    is exactly what gets sent to the tenant and must stay free of this framing.
    """
    original = (original_text or "").strip()
    if not original:
        return None
    return f'Replying to: "{original}"'


def _planner_draft_status_and_schedule(
    db: Session,
    *,
    channel: str,
    planner_mode: str,
    ai_settings: TenantAiSettings,
    result,
) -> tuple[str, datetime | None]:
    """Shared status/schedule decision for a planner-produced draft.

    A draft the checker never approved is stored as `needs_review` so staff still see it, but it
    is deliberately kept out of the auto-send path regardless of the tenant's auto_send setting.
    Same for any draft generated under "auto-draft" mode: even an approved one never auto-sends.
    """
    auto_send_enabled = planner_mode == "auto-send" and (
        (ai_settings.auto_send_email if channel == "email" else ai_settings.auto_send_whatsapp)
        and result.auto_send_allowed
    )

    if result.status == STATUS_NEEDS_REVIEW and not result.auto_send_allowed:
        status_value = "needs_review"
    else:
        status_value = "pending_auto_send" if auto_send_enabled else "pending"

    scheduled_send_at = (
        datetime.now(timezone.utc) + timedelta(seconds=_auto_send_delay_seconds(db))
        if status_value == "pending_auto_send"
        else None
    )
    return status_value, scheduled_send_at


def apply_planner_result_to_draft(
    db: Session,
    draft: AiAutoDraft,
    *,
    tenant: Tenant,
    ai_settings: TenantAiSettings,
    channel: str,
    result,
    inbound_text: str | None,
) -> AiAutoDraft:
    planner_mode = ai_settings.planner_mode or "off"
    status_value, scheduled_send_at = _planner_draft_status_and_schedule(
        db,
        channel=channel,
        planner_mode=planner_mode,
        ai_settings=ai_settings,
        result=result,
    )
    draft.generated_text = result.generated_text or ""
    draft.quoted_context = _build_quoted_context(inbound_text)
    draft.template_id = result.template_id
    draft.status = status_value
    draft.scheduled_send_at = scheduled_send_at
    draft.agent_run_id = result.run_id
    draft.checker_feedback = result.checker_feedback
    return draft


def _generate_draft_via_planner(
    db: Session,
    trigger: AiAutoDraftTrigger,
    tenant: Tenant,
    ai_settings: TenantAiSettings,
) -> AiAutoDraft | None:
    """Auto-draft/auto-send drafting: the planner chooses the template instead of the tenant default."""
    planner_mode = ai_settings.planner_mode or "off"
    inbound_text = ai_agent_orchestrator.latest_inbound_text(db, tenant.id, trigger.channel)
    result = ai_agent_orchestrator.run_planner_loop(
        db,
        tenant=tenant,
        channel=trigger.channel,
        mode=planner_mode,
        inbound_text=inbound_text,
    )
    if not result.generated_text:
        logger.info(
            "Planner produced no draft tenant_id=%s channel=%s status=%s reason=%s",
            tenant.id,
            trigger.channel,
            result.status,
            result.escalation_reason,
        )
        return None

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel=trigger.channel,
        template_id=result.template_id,
        email_thread_id=trigger.email_thread_id,
        whatsapp_endpoint_id=trigger.whatsapp_endpoint_id,
        generated_text=result.generated_text or "",
        quoted_context=_build_quoted_context(inbound_text),
        status="pending",
        scheduled_send_at=None,
        agent_run_id=result.run_id,
        checker_feedback=result.checker_feedback,
    )
    apply_planner_result_to_draft(
        db,
        draft,
        tenant=tenant,
        ai_settings=ai_settings,
        channel=trigger.channel,
        result=result,
        inbound_text=inbound_text,
    )
    db.add(draft)
    return draft


def regenerate_draft_via_planner(db: Session, draft: AiAutoDraft, instructions: str) -> AiAutoDraft | None:
    """Re-runs the planner/drafter/checker loop for an existing draft, folding in admin
    instructions from a "REDO-{id} <instructions>" reply, and updates the draft in place.

    Returns None (without mutating `draft`) if the tenant/settings can't be resolved or the
    planner produces nothing, so a failed redo leaves the original draft intact and still
    actionable. Never leaves a redo in `pending_auto_send`: the admin explicitly asked for a
    change, so it always needs a fresh human look before sending.
    """
    tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
    if tenant is None:
        return None

    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    if ai_settings is None:
        return None

    planner_mode = ai_settings.planner_mode or "off"
    inbound_text = ai_agent_orchestrator.latest_inbound_text(db, tenant.id, draft.channel)
    result = ai_agent_orchestrator.run_planner_loop(
        db,
        tenant=tenant,
        channel=draft.channel,
        mode=planner_mode,
        inbound_text=inbound_text,
        operator_note=instructions,
    )
    if not result.generated_text:
        logger.info(
            "Redo planner produced no draft draft_id=%s tenant_id=%s channel=%s status=%s reason=%s",
            draft.id,
            tenant.id,
            draft.channel,
            result.status,
            result.escalation_reason,
        )
        return None

    apply_planner_result_to_draft(
        db,
        draft,
        tenant=tenant,
        ai_settings=ai_settings,
        channel=draft.channel,
        result=result,
        inbound_text=inbound_text,
    )
    # A redo never auto-sends, regardless of what the fresh checker pass would have allowed.
    if draft.status == "pending_auto_send":
        draft.status = "pending"
    draft.scheduled_send_at = None
    return draft


def generate_draft_for_trigger(db: Session, trigger: AiAutoDraftTrigger) -> AiAutoDraft | None:
    """Generate the auto-draft a due trigger represents.

    Returns None (without raising) for any state that makes generation impossible or
    pointless - tenant/settings/template missing - so the scheduler can just skip and move on.
    Does not commit; the caller (the scheduler sweep) owns the transaction per trigger.
    """
    tenant = db.query(Tenant).filter(Tenant.id == trigger.tenant_id).first()
    if tenant is None:
        return None

    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    if ai_settings is None:
        return None

    if trigger.channel == "email" and trigger.email_thread_id is not None:
        link = (
            db.query(TenantConversationLink)
            .filter(TenantConversationLink.tenant_id == tenant.id)
            .filter(TenantConversationLink.conversation_id == trigger.email_thread_id)
            .filter(TenantConversationLink.unlinked_at.is_(None))
            .first()
        )
        if link is not None and not link.is_visible:
            return None

    if (ai_settings.planner_mode or "off") in ("auto-draft", "auto-send"):
        return _generate_draft_via_planner(db, trigger, tenant, ai_settings)

    template_id = ai_settings.default_email_template_id if trigger.channel == "email" else ai_settings.default_whatsapp_template_id
    if template_id is None:
        logger.info("Skipping AI auto-draft: no default template configured tenant_id=%s channel=%s", tenant.id, trigger.channel)
        return None

    template = db.query(AiReplyTemplate).filter(AiReplyTemplate.id == template_id).first()
    if template is None:
        return None

    blocks, agent_instructions = ai_agent_orchestrator.resolve_drafter_context(
        db, ai_settings.drafter_profile_id
    )
    inbound_text = ai_agent_orchestrator.latest_inbound_text(db, tenant.id, trigger.channel)
    generated_text = ai_reply_service.build_prompt_and_generate(
        db,
        tenant=tenant,
        template=template,
        channel=trigger.channel,
        rough_draft=None,
        inbound_text=inbound_text,
        blocks=blocks,
        agent_instructions=agent_instructions,
    )

    auto_send_enabled = ai_settings.auto_send_email if trigger.channel == "email" else ai_settings.auto_send_whatsapp
    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel=trigger.channel,
        template_id=template.id,
        email_thread_id=trigger.email_thread_id,
        whatsapp_endpoint_id=trigger.whatsapp_endpoint_id,
        generated_text=generated_text,
        quoted_context=_build_quoted_context(inbound_text),
        status="pending_auto_send" if auto_send_enabled else "pending",
        scheduled_send_at=(datetime.now(timezone.utc) + timedelta(seconds=_auto_send_delay_seconds(db))) if auto_send_enabled else None,
    )
    db.add(draft)
    return draft


def _send_email_draft(db: Session, draft: AiAutoDraft) -> bool:
    if draft.email_thread_id is None:
        logger.warning("Cannot auto-send email draft without an email_thread_id draft_id=%s", draft.id)
        return False

    conversation = db.query(Conversation).filter(Conversation.id == draft.email_thread_id).first()
    if conversation is None:
        return False
    account = db.query(GmailAccount).filter(GmailAccount.id == conversation.provider_account_id).first()
    if account is None or not account.is_active:
        return False

    latest_message = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.sent_at.desc())
        .first()
    )
    to_email = None
    in_reply_to_message_id = None
    references = None
    if latest_message:
        if latest_message.direction == "inbound" and latest_message.sender_email:
            to_email = latest_message.sender_email
        elif latest_message.direction == "outbound" and latest_message.recipient_email:
            to_email = latest_message.recipient_email
        if isinstance(latest_message.raw_payload, dict):
            headers = (latest_message.raw_payload.get("gmail", {}).get("payload") or {}).get("headers") or []
            for header in headers:
                if str(header.get("name", "")).lower() == "message-id":
                    in_reply_to_message_id = str(header.get("value", "")).strip()
                elif str(header.get("name", "")).lower() == "references":
                    references = str(header.get("value", "")).strip()
    if is_own_mailbox_address(db, to_email):
        logger.warning("Resolved recipient %s for draft_id=%s is one of our own Gmail mailboxes; refusing to send", to_email, draft.id)
        to_email = None
    if not to_email:
        logger.warning("Cannot auto-send email draft: no recipient resolved draft_id=%s", draft.id)
        return False

    credentials = build_gmail_credentials(account)
    if not credentials:
        logger.warning("Cannot auto-send email draft: Gmail credentials unavailable draft_id=%s", draft.id)
        return False

    try:
        gmail_result = send_gmail_reply(
            credentials,
            thread_id=conversation.provider_thread_id,
            to_email=to_email,
            subject=conversation.subject or "",
            body_text=draft.generated_text,
            from_email=account.email_address,
            in_reply_to_message_id=in_reply_to_message_id,
            references=references,
        )
    except Exception:
        logger.exception("AI auto-send failed to send Gmail reply draft_id=%s", draft.id)
        return False

    communication = persist_gmail_outbound_message(
        db,
        tenant_id=draft.tenant_id,
        conversation=conversation,
        account=account,
        to_email=to_email,
        subject=conversation.subject or "",
        message=draft.generated_text,
        gmail_result=gmail_result,
        ai_generated=True,
    )
    draft.sent_communication_id = communication.id
    return True


def _resolve_whatsapp_endpoint(db: Session, draft: AiAutoDraft) -> TenantChannelEndpoint | None:
    if draft.whatsapp_endpoint_id is not None:
        endpoint = db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.id == draft.whatsapp_endpoint_id).first()
        if endpoint is not None and endpoint.is_active:
            return endpoint

    # No endpoint captured at trigger time - only safe to guess when the tenant has exactly one
    # active WhatsApp endpoint; multiple candidates means we can't tell which chat to reply in.
    active_endpoints = (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.tenant_id == draft.tenant_id,
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.is_active.is_(True),
        )
        .all()
    )
    return active_endpoints[0] if len(active_endpoints) == 1 else None


def _send_whatsapp_draft(db: Session, draft: AiAutoDraft) -> bool:
    endpoint = _resolve_whatsapp_endpoint(db, draft)
    if endpoint is None:
        logger.warning("Cannot auto-send WhatsApp draft: no unambiguous WhatsApp endpoint draft_id=%s", draft.id)
        return False

    tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
    if tenant is None:
        return False

    whatsapp_to = endpoint.external_chat_namespace or get_tenant_primary_phone_raw(db, tenant)
    if not whatsapp_to:
        logger.warning("Cannot auto-send WhatsApp draft: no destination chat/phone draft_id=%s", draft.id)
        return False

    try:
        whatsapp_result = asyncio.run(
            send_whatsapp_message(
                {
                    "to": whatsapp_to,
                    "message": draft.generated_text,
                    "tenant_id": draft.tenant_id,
                    "whatsapp_endpoint_id": endpoint.id,
                    "external_account_id": endpoint.external_account_id,
                }
            )
        )
    except Exception:
        logger.exception("AI auto-send failed to send WhatsApp message draft_id=%s", draft.id)
        return False

    persistence_result = persist_whatsapp_outbound_communication(
        db,
        tenant_id=draft.tenant_id,
        provider=endpoint.provider,
        external_account_id=endpoint.external_account_id,
        external_phone_id=endpoint.external_phone_id,
        external_chat_namespace=endpoint.external_chat_namespace,
        whatsapp_chat_id=(whatsapp_result.get("whatsapp_chat_id") if isinstance(whatsapp_result, dict) else None),
        whatsapp_identity_key=(whatsapp_result.get("whatsapp_identity_key") if isinstance(whatsapp_result, dict) else None),
        whatsapp_normalized_phone=(whatsapp_result.get("whatsapp_normalized_phone") if isinstance(whatsapp_result, dict) else None),
        provider_message_id=(
            (whatsapp_result.get("whatsapp_message_id") if isinstance(whatsapp_result, dict) else None)
            or (whatsapp_result.get("provider_message_id") if isinstance(whatsapp_result, dict) else None)
        ),
        subject=None,
        message=draft.generated_text,
        created_at=datetime.now(timezone.utc),
        ai_generated=True,
    )
    draft.sent_communication_id = persistence_result.communication.id
    return True


def send_scheduled_draft(
    db: Session, draft: AiAutoDraft, *, resolution_source: str = "human_ui", reason: str | None = None
) -> bool:
    """Sends a `pending_auto_send` draft via the same primitives manual sends use.

    Returns True and mutates draft.status/sent_communication_id on success; on failure the
    draft is left as `pending_auto_send` (unlogged failures would otherwise silently drop a
    reply the tenant is waiting on) so it's retried on the next scheduler sweep, and still
    visible/actionable (dismiss/use manually) in the pending-drafts UI in the meantime.

    `resolution_source`/`reason` record why this send happened - "human_ui" (CRM button),
    "human_whatsapp" (a YES-{id} reply), or "auto_timer" (the scheduler, no human involved).
    The auto-timer path has no explicit reason of its own, so it falls back to the checker's
    feedback - the reason a draft was allowed to auto-send in the first place.
    """
    sent = _send_email_draft(db, draft) if draft.channel == "email" else _send_whatsapp_draft(db, draft)
    if not sent:
        return False
    draft.status = "sent"
    draft.resolution_source = resolution_source
    draft.resolution_reason = reason or (draft.checker_feedback if resolution_source == "auto_timer" else None)
    return True
