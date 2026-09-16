import asyncio
import base64
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import STATUS_GENERATING, AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.ai_agent_run import STATUS_ESCALATED, STATUS_NEEDS_REVIEW, AiAgentRun
from app.models.ai_reply_template import AiReplyTemplate
from app.models.redo_request_log import RedoRequestLog
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services import ai_agent_orchestrator, ai_reply_service, tenant_files_storage
from app.services.attachment_service import OutboundAttachment, load_outbound_attachments
from app.services import beds24_service
from app.services.beds24_sync import sync_tenant_from_beds24_booking
from app.services.email_outbound_persistence import is_own_mailbox_address, persist_gmail_outbound_message
from app.services.gmail_client import build_gmail_credentials, send_gmail_reply
from app.services.tenant_phone_aliases import get_tenant_primary_phone_raw
from app.services.whatsapp_client import send_whatsapp_message
from app.services.whatsapp_outbound_persistence import persist_whatsapp_outbound_communication

logger = logging.getLogger(__name__)


def _auto_send_delay_seconds(db: Session) -> int:
    settings = db.query(AdminSettings).first()
    return settings.ai_auto_send_delay_seconds if settings is not None else 300


def expire_stale_generating_drafts(db: Session, timeout_seconds: int) -> int:
    """Rescue drafts stuck in "generating" because their background planner run never finished
    (e.g. the process was restarted mid-run). Without this, such a draft would show a spinner in
    the UI forever. Any generating draft older than timeout_seconds is flipped to needs_review so
    a human can retry it. Returns the number of drafts reclassified.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    stale = (
        db.query(AiAutoDraft)
        .filter(AiAutoDraft.status == STATUS_GENERATING, AiAutoDraft.created_at < cutoff)
        .all()
    )
    for draft in stale:
        draft.status = STATUS_NEEDS_REVIEW
        draft.generated_text = draft.generated_text or ""
        draft.checker_feedback = "Draft generation did not finish."
    if stale:
        db.commit()
    return len(stale)


def _build_quoted_context(original_text: str | None) -> str | None:
    """The inbound message a draft answers, framed for human display (e.g. in the WhatsApp
    approval ping or the AI Drafts page) - never appended to generated_text, since that column
    is exactly what gets sent to the tenant and must stay free of this framing.
    """
    original = (original_text or "").strip()
    if not original:
        return None
    return f'Replying to: "{original}"'


def _resolve_executor_mode(db: Session, tenant_id: int) -> str:
    """"manual" (validate on human approval, then push) or "autonomous" (validate and push
    without a human). A tenant's own TenantAiSettings.executor_mode wins; NULL falls back to
    AdminSettings.executor_default_mode, which ships "manual" so no tenant starts pushing to
    Beds24 unattended without an explicit opt-in."""
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if ai_settings is not None and ai_settings.executor_mode:
        return ai_settings.executor_mode
    admin_settings = db.query(AdminSettings).first()
    return (admin_settings.executor_default_mode if admin_settings is not None else None) or "manual"


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
    A draft carrying a prepared Beds24 write (sales manager execute=true) never auto-sends in
    manual executor mode, regardless of the tenant's auto_send setting - that write only ever
    happens once a human approves it (see send_scheduled_draft). Autonomous executor mode allows
    it into pending_auto_send like any other approved draft; the executor itself still validates
    (and can still block) the write when the timer actually sends it.
    """
    has_pending_execution = bool(getattr(result, "pending_execution", None))
    executor_blocks_auto_send = has_pending_execution and _resolve_executor_mode(db, ai_settings.tenant_id) != "autonomous"
    auto_send_enabled = (
        planner_mode == "auto-send"
        and not executor_blocks_auto_send
        and (
            (ai_settings.auto_send_email if channel == "email" else ai_settings.auto_send_whatsapp)
            and result.auto_send_allowed
        )
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
    # The planner may have re-targeted the reply to a different channel (automated paths only);
    # the draft's status/schedule and send target must follow that new channel, not the one the
    # trigger arrived on.
    effective_channel = getattr(result, "chosen_channel", None) or channel
    status_value, scheduled_send_at = _planner_draft_status_and_schedule(
        db,
        channel=effective_channel,
        planner_mode=planner_mode,
        ai_settings=ai_settings,
        result=result,
    )
    draft.generated_text = result.generated_text or ""
    draft.formatted_text = result.formatted_text
    draft.quoted_context = _build_quoted_context(inbound_text)
    draft.template_id = result.template_id
    draft.status = status_value
    draft.scheduled_send_at = scheduled_send_at
    draft.agent_run_id = result.run_id
    draft.checker_feedback = result.checker_feedback
    # Prepared by the sales manager (execute=true); validated and pushed to Beds24 by the
    # executor agent - see send_scheduled_draft / _execute_pending. A staged write starts life
    # "pending" so it surfaces as its own approval in the AI Drafts Beds24 column.
    draft.pending_execution = getattr(result, "pending_execution", None)
    draft.execution_status = "pending" if draft.pending_execution else None
    if getattr(result, "chosen_channel", None):
        draft.channel = result.chosen_channel
        draft.email_thread_id = result.chosen_email_thread_id
        draft.whatsapp_endpoint_id = result.chosen_whatsapp_endpoint_id
    # Store the quotation PDF's path (not its bytes) so it can be attached to the outgoing
    # message at send time - including a delayed auto-send, which reads the file by path then.
    draft.quotation_file_path = getattr(result, "quotation_file_path", None)
    draft.quotation_filename = getattr(result, "quotation_pdf_filename", None) if draft.quotation_file_path else None
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
        respect_planner_channel=True,
        outbound_email_thread_id=trigger.email_thread_id,
        outbound_whatsapp_endpoint_id=trigger.whatsapp_endpoint_id,
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
        formatted_text=result.formatted_text,
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


def _redo_instruction_block(
    what: str, why: str | None, *, redo_number: int, draft_snapshot: str | None = None
) -> str:
    block = f"Redo #{redo_number}"
    snapshot = (draft_snapshot or "").strip()
    if snapshot:
        # Show the planner the exact draft this redo was asked to change, so it edits
        # that text rather than regenerating from scratch and drifting away from it.
        block += f"\nPrevious draft:\n{snapshot}"
    block += f"\nWhat: {what}"
    if why:
        block += f"\nWhy: {why}"
    return block


def regenerate_draft_via_planner(
    db: Session, draft: AiAutoDraft, what: str, why: str | None, current_draft: str | None = None
) -> AiAutoDraft | None:
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
    # Resolve the current draft snapshot before apply_planner_result_to_draft overwrites it.
    # Prefer what the caller supplied (the frontend sends formatted_text); otherwise fall back
    # to the draft's own text so entry points without a frontend (WhatsApp) still ground the redo.
    current_snapshot = current_draft or draft.formatted_text or draft.generated_text
    prior_redo_logs = (
        db.query(RedoRequestLog)
        .filter(RedoRequestLog.ai_auto_draft_id == draft.id)
        .order_by(RedoRequestLog.created_at.asc(), RedoRequestLog.id.asc())
        .all()
    )
    operator_note = "\n\n".join(
        [
            *[
                _redo_instruction_block(
                    prior_log.what,
                    prior_log.why,
                    redo_number=index,
                    draft_snapshot=prior_log.previous_draft_text,
                )
                for index, prior_log in enumerate(prior_redo_logs, start=1)
            ],
            _redo_instruction_block(
                what, why, redo_number=len(prior_redo_logs) + 1, draft_snapshot=current_snapshot
            ),
        ]
    )
    result = ai_agent_orchestrator.run_planner_loop(
        db,
        tenant=tenant,
        channel=draft.channel,
        mode=planner_mode,
        inbound_text=inbound_text,
        operator_note=operator_note,
        is_redo=True,
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
        drafter_profile_id=ai_settings.drafter_profile_id,
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


def _draft_quotation_attachments(db: Session, draft: AiAutoDraft) -> list[OutboundAttachment]:
    """Load the sales-manager PDF (if any) linked to this draft, for attaching at send time.

    Reads bytes lazily by path (the current flow) so a delayed auto-send still attaches the file
    without it ever being carried through the draft row; quotation_attachment_id is a fallback for
    drafts created before this flow existed.
    """
    if draft.quotation_file_path:
        try:
            path = tenant_files_storage.resolve_download_path(draft.quotation_file_path)
            return [
                OutboundAttachment(
                    attachment_id=0,
                    filename=draft.quotation_filename or path.name,
                    mime_type="application/pdf",
                    content=path.read_bytes(),
                )
            ]
        except Exception:
            # A missing/oversized quotation must not block the reply itself - log and send without it.
            logger.exception("Could not load quotation file for draft_id=%s path=%s", draft.id, draft.quotation_file_path)
            return []
    if not draft.quotation_attachment_id:
        return []
    try:
        return load_outbound_attachments(
            db,
            tenant_id=draft.tenant_id,
            attachment_ids=[draft.quotation_attachment_id],
            channel=draft.channel,
        )
    except Exception:
        logger.exception("Could not load quotation attachment for draft_id=%s", draft.id)
        return []


def _send_email_draft(db: Session, draft: AiAutoDraft) -> tuple[bool, str | None]:
    if draft.email_thread_id is None:
        logger.warning("Cannot auto-send email draft without an email_thread_id draft_id=%s", draft.id)
        return False, "No email thread is linked for this draft"

    conversation = db.query(Conversation).filter(Conversation.id == draft.email_thread_id).first()
    if conversation is None:
        logger.warning("Cannot auto-send email draft: email thread not found draft_id=%s email_thread_id=%s", draft.id, draft.email_thread_id)
        return False, "Email thread for this draft could not be found"
    account = db.query(GmailAccount).filter(GmailAccount.id == conversation.provider_account_id).first()
    if account is None or not account.is_active:
        logger.warning("Cannot auto-send email draft: Gmail account inactive draft_id=%s account_id=%s", draft.id, conversation.provider_account_id)
        return False, "Gmail account for this thread is inactive"

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
        return False, "Could not determine a recipient email for this thread (its email links may be inactive, e.g. after a cancellation)"

    credentials = build_gmail_credentials(account)
    if not credentials:
        logger.warning("Cannot auto-send email draft: Gmail credentials unavailable draft_id=%s", draft.id)
        return False, "Gmail credentials are unavailable for this thread"

    try:
        gmail_result = send_gmail_reply(
            credentials,
            thread_id=conversation.provider_thread_id,
            to_email=to_email,
            subject=conversation.subject or "",
            body_text=draft.generated_text,
            body_html=draft.formatted_text or None,
            from_email=account.email_address,
            in_reply_to_message_id=in_reply_to_message_id,
            references=references,
            attachments=_draft_quotation_attachments(db, draft),
        )
    except Exception:
        logger.exception("AI auto-send failed to send Gmail reply draft_id=%s", draft.id)
        return False, "Failed to send Gmail reply"

    try:
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
    except Exception:
        logger.exception("AI auto-send Gmail persistence failed draft_id=%s", draft.id)
    return True, None


def _resolve_whatsapp_endpoint(db: Session, draft: AiAutoDraft) -> tuple[TenantChannelEndpoint | None, str | None]:
    if draft.whatsapp_endpoint_id is not None:
        endpoint = db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.id == draft.whatsapp_endpoint_id).first()
        if endpoint is not None and endpoint.is_active:
            return endpoint, None

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
    if len(active_endpoints) == 1:
        return active_endpoints[0], None
    if len(active_endpoints) == 0:
        return None, "No WhatsApp chat is linked for this draft - link one first"
    return None, "This tenant has multiple WhatsApp chats linked; link a specific one for this draft"


def _send_whatsapp_draft(db: Session, draft: AiAutoDraft) -> tuple[bool, str | None]:
    endpoint, endpoint_reason = _resolve_whatsapp_endpoint(db, draft)
    if endpoint is None:
        logger.warning("Cannot auto-send WhatsApp draft: no unambiguous WhatsApp endpoint draft_id=%s", draft.id)
        return False, endpoint_reason

    tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
    if tenant is None:
        return False, "Tenant for this draft could not be found"

    whatsapp_to = endpoint.external_chat_namespace or get_tenant_primary_phone_raw(db, tenant)
    if not whatsapp_to:
        logger.warning("Cannot auto-send WhatsApp draft: no destination chat/phone draft_id=%s", draft.id)
        return False, "Could not determine a destination WhatsApp chat or phone for this draft"

    message = draft.generated_text
    if draft.formatted_text:
        if ai_agent_orchestrator.formatter_output_looks_like_html(draft.formatted_text):
            logger.warning(
                "WhatsApp auto-draft formatted_text looks like HTML; falling back to generated_text draft_id=%s",
                draft.id,
            )
        else:
            message = draft.formatted_text
    quotation_attachments = [
        {
            "filename": item.filename,
            "mime_type": item.mime_type,
            "data_base64": base64.b64encode(item.content).decode("ascii"),
        }
        for item in _draft_quotation_attachments(db, draft)
    ]
    try:
        whatsapp_result = asyncio.run(
            send_whatsapp_message(
                {
                    "to": whatsapp_to,
                    "message": message,
                    "tenant_id": draft.tenant_id,
                    "whatsapp_endpoint_id": endpoint.id,
                    "external_account_id": endpoint.external_account_id,
                    "attachments": quotation_attachments,
                }
            )
        )
    except Exception:
        logger.exception("AI auto-send failed to send WhatsApp message draft_id=%s", draft.id)
        return False, "Failed to send WhatsApp message"

    try:
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
            message=message,
            created_at=datetime.now(timezone.utc),
            ai_generated=True,
        )
        draft.sent_communication_id = persistence_result.communication.id
    except Exception:
        logger.exception("AI auto-send WhatsApp persistence failed draft_id=%s", draft.id)
    return True, None


def _execute_update(booking_id: str, invoice_items: list[dict]) -> str | None:
    try:
        asyncio.run(
            beds24_service.update_booking_invoice_items(
                booking_id=booking_id,
                original_invoice_item_ids=[],
                final_invoice_items=[
                    {
                        "type": item.get("type"),
                        "description": item.get("description") or "",
                        "qty": item.get("qty") or 1,
                        "amount": item.get("amount") or 0,
                        "vatRate": item.get("vat_rate") or 0,
                    }
                    for item in invoice_items
                ],
            )
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the approver, not swallowed
        logger.exception("Beds24 update push failed booking_id=%s", booking_id)
        return str(getattr(exc, "detail", None) or exc)
    return None


def _execute_create(create_payload: dict) -> tuple[str | None, str | None]:
    """Returns (new_booking_id, failure_reason)."""
    room_id = create_payload.get("room_id")
    if not room_id:
        return None, "The prepared booking is missing a room - cannot create it in Beds24"
    payload = {
        "roomId": room_id,
        "arrival": create_payload.get("arrival"),
        "departure": create_payload.get("departure"),
        "status": create_payload.get("status") or "inquiry",
        "firstName": create_payload.get("first_name") or "",
        "lastName": create_payload.get("last_name") or "",
        "email": create_payload.get("email") or "",
        "phone": create_payload.get("phone") or "",
        "numAdult": create_payload.get("num_adults") or 1,
        "numChild": create_payload.get("num_children") or 0,
        "invoiceItems": [
            {
                "type": item.get("type"),
                "description": item.get("description") or "",
                "qty": item.get("qty") or 1,
                "amount": item.get("amount") or 0,
                "vatRate": item.get("vat_rate") or 0,
            }
            for item in (create_payload.get("invoice_items") or [])
        ],
    }
    try:
        new_booking_id = asyncio.run(beds24_service.create_booking(payload))
    except Exception as exc:  # noqa: BLE001 - surfaced to the approver, not swallowed
        logger.exception("Beds24 booking create failed")
        return None, str(getattr(exc, "detail", None) or exc)
    return new_booking_id, None


def _execute_pending(db: Session, draft: AiAutoDraft, *, resolution_source: str) -> str | None:
    """Validates (via the executor agent) and, if approved, applies a Beds24 write the sales
    manager prepared for this draft (draft.pending_execution) - before the draft itself is sent,
    so the reply is never sent describing a quote that wasn't actually applied. Returns a failure
    reason on error/rejection, or None on success (also clearing draft.pending_execution).
    """
    pending = draft.pending_execution
    if not pending:
        return None
    tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
    if tenant is None:
        return "Tenant for this draft could not be found"

    result, run_id = ai_agent_orchestrator.run_executor_validation(
        db,
        tenant=tenant,
        pending_execution=pending,
        price_context=draft.quoted_context or "",
    )
    draft.executor_run_id = run_id
    if not result.approved:
        draft.execution_status = "failed"
        return result.reason or "The executor did not approve this action"

    action = pending.get("action")
    if action == "create":
        new_booking_id, failure = _execute_create(pending.get("create_payload") or {})
        if failure:
            draft.execution_status = "failed"
            return failure
        # Re-fetch and materialise the new booking as a Tenant + Finance rows, the same
        # deterministic sync app.api.quotation.create_quotation_beds24_booking uses - this does
        # not touch `tenant` (the conversation this draft answers) since the new booking is its
        # own tenant record.
        synced = asyncio.run(sync_tenant_from_beds24_booking(db, new_booking_id))
    else:
        booking_id = pending.get("booking_id")
        if not booking_id:
            draft.execution_status = "failed"
            return "Prepared Beds24 update is missing a booking id"
        failure = _execute_update(booking_id, pending.get("invoice_items") or [])
        if failure:
            draft.execution_status = "failed"
            return failure
        # Re-fetch and rewrite Tenant/Finance deterministically, the same as the Quotation
        # Manager's own invoice-items push does (app.api.quotation.send_quotation_invoice_items_to_beds24).
        synced = asyncio.run(sync_tenant_from_beds24_booking(db, booking_id))

    if synced is None:
        draft.execution_status = "failed"
        logger.warning("Beds24 accepted the prepared action but re-sync failed draft_id=%s", draft.id)
        return "Beds24 accepted the action but the booking could not be re-synced"
    draft.pending_execution = None
    draft.execution_status = "executed"
    return None


def execute_pending_now(
    db: Session, draft: AiAutoDraft, *, resolution_source: str = "human_ui"
) -> tuple[bool, str | None]:
    """Approve + push the Beds24 action staged on this draft on its own, without sending the
    message reply - the two are separate approvals in the AI Drafts UI. Runs the executor
    validation and, if approved, performs the Beds24 write (via _execute_pending, which sets
    execution_status). Returns (True, None) on success or (False, reason) on rejection/failure.
    The caller commits.
    """
    if not draft.pending_execution:
        return False, "This draft has no Beds24 action to approve"
    failure = _execute_pending(db, draft, resolution_source=resolution_source)
    if failure:
        return False, failure
    return True, None


def reject_pending_execution(
    db: Session, draft: AiAutoDraft, *, reason: str | None = None, resolution_source: str = "human_ui"
) -> None:
    """Drop the Beds24 action staged on this draft without pushing it, keeping the message draft
    intact so the reply can still be sent or edited separately (decoupled approvals). Recorded as
    an escalated executor AiAgentRun so the rejection shows up in the same audit trail the
    executor's own verdicts use. The caller commits.
    """
    if not draft.pending_execution:
        return
    run = AiAgentRun(
        tenant_id=draft.tenant_id,
        channel="beds24",
        mode="executor",
        status=STATUS_ESCALATED,
        escalation_reason="human_rejected",
        final_text=(reason or "").strip() or "Beds24 action rejected by a human in the AI Drafts UI",
    )
    db.add(run)
    db.flush()
    draft.executor_run_id = run.id
    draft.execution_status = "rejected"
    draft.pending_execution = None


def send_scheduled_draft(
    db: Session,
    draft: AiAutoDraft,
    *,
    resolution_source: str = "human_ui",
    reason: str | None = None,
    run_pending_execution: bool | None = None,
) -> tuple[bool, str | None]:
    """Sends a `pending_auto_send` draft via the same primitives manual sends use.

    Returns True and mutates draft.status/sent_communication_id on success; on failure the
    draft is left as `pending_auto_send` (unlogged failures would otherwise silently drop a
    reply the tenant is waiting on) so it's retried on the next scheduler sweep, and still
    visible/actionable (dismiss/use manually) in the pending-drafts UI in the meantime.

    `resolution_source`/`reason` record why this send happened - "human_ui" (CRM button),
    "human_whatsapp" (a YES-{id} reply), or "auto_timer" (the scheduler, no human involved).
    The auto-timer path has no explicit reason of its own, so it falls back to the checker's
    feedback - the reason a draft was allowed to auto-send in the first place.

    A draft carrying a prepared Beds24 write (sales manager execute=true) may be validated by the
    executor agent and pushed here, before the reply is sent. Whether that push runs alongside the
    send depends on the source (or an explicit run_pending_execution override): the CRM message
    "Send" (human_ui) sends the reply only - the Beds24 push is a separate approval in the AI
    Drafts UI (execute_pending_now) - while a WhatsApp YES keeps its original coupled behaviour and
    the autonomous timer still pushes without a human. In manual executor mode the auto_timer path
    never pushes (such a draft never reaches pending_auto_send, see _planner_draft_status_and_
    schedule, but this is checked again as a defensive second gate). When the push does run, a
    rejection/failure blocks the send entirely.
    """
    if draft.pending_execution:
        executor_mode = _resolve_executor_mode(db, draft.tenant_id)
        if resolution_source == "auto_timer" and executor_mode != "autonomous":
            return False, "This draft has a Beds24 action staged and needs human approval before it can send"
        # Decoupled approvals: only the WhatsApp/auto-timer paths still run the coupled push; the
        # CRM "Send" leaves the staged Beds24 action for its own approval column.
        if run_pending_execution is None:
            run_pending_execution = resolution_source != "human_ui"
        if run_pending_execution:
            execution_failure = _execute_pending(db, draft, resolution_source=resolution_source)
            if execution_failure:
                return False, execution_failure

    sent, failure_reason = _send_email_draft(db, draft) if draft.channel == "email" else _send_whatsapp_draft(db, draft)
    if not sent:
        return False, failure_reason
    draft.status = "sent"
    draft.resolution_source = resolution_source
    draft.resolution_reason = reason or (draft.checker_feedback if resolution_source == "auto_timer" else None)
    return True, None
