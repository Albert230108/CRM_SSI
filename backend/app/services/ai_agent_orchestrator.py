"""The planner -> drafter -> checker loop.

A single entry point, `run_planner_loop`, owns the whole decision: which template fits the
conversation, what extra knowledge to pull from the brain, what extra instruction the drafter
needs, and whether the resulting draft is good enough to hand over. Every model call is recorded
on an `AiAgentRun` so an operator can audit the choice after the fact.

The loop never sends anything. It returns text plus a status; persisting a draft, showing it in
the reply box, or scheduling an auto-send is the caller's job.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.ai_agent_profile import (
    CHECKER_ROLE,
    DRAFTER_ROLE,
    FORMATTER_ROLE,
    PLANNER_ROLE,
    SALES_MANAGER_ROLE,
    AiAgentProfile,
)
from app.models.ai_agent_run import (
    STATUS_COMPLETED,
    STATUS_ESCALATED,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_SKIPPED,
    AiAgentRun,
    AiAgentRunStep,
)
from app.models.ai_reply_template import AiReplyTemplate
from app.models.gmail_integration import ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import ai_prompt_blocks, ai_reply_service, attachment_service, brain_service, gemini_client
from app.services.datetime_placeholders import resolve_datetime_placeholders
from app.services.thread_timeline_service import load_tenant_whatsapp_messages
from app.services import outbound_target_resolver, sales_manager_service

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[A-Za-z][^>]*>")

PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "should_reply": {"type": "boolean"},
        # Which channel the reply should go out on. Optional: when omitted or unrecognised the
        # reply follows the channel the conversation arrived on (the historical behaviour). When
        # the planner names one, automated paths honour it and re-target the send accordingly.
        "channel": {"type": ["string", "null"]},
        "template_id": {"type": ["integer", "null"]},
        "extra_brain_sections": {"type": "array", "items": {"type": "string"}},
        "extra_instructions": {"type": "string"},
        # Optional. Set needed=true to have the sales-manager agent price and/or render a PDF
        # quotation before the reply is drafted. `scope` is "price" (numbers for the reply only),
        # "pdf" (also render+file+attach the PDF), or "both". The remaining fields are the exact
        # booking parameters to quote; leave any unknown and the tenant's booking is used.
        "sales_request": {
            "type": "object",
            "properties": {
                "needed": {"type": "boolean"},
                "scope": {"type": "string"},
                "property_name": {"type": ["string", "null"]},
                "room_name": {"type": ["string", "null"]},
                "check_in": {"type": ["string", "null"]},
                "check_out": {"type": ["string", "null"]},
                "adults": {"type": ["integer", "null"]},
                "children": {"type": ["integer", "null"]},
                "security_deposit": {"type": ["number", "null"]},
                "notes": {"type": ["string", "null"]},
            },
        },
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "template_id": {"type": "integer"},
                    "why_not": {"type": "string"},
                },
                "required": ["template_id", "why_not"],
            },
        },
    },
    "required": ["should_reply", "template_id", "extra_instructions", "confidence", "reasoning"],
}

CHECKER_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "feedback": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "extra_brain_sections": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["passed", "feedback"],
}

FORMATTER_SCHEMA = {
    "type": "object",
    "properties": {
        "formatted_text": {"type": "string"},
    },
    "required": ["formatted_text"],
}

SALES_MANAGER_SCHEMA = {
    "type": "object",
    "properties": {
        # A short, factual price summary written for the guest, grounded on the charge lines the
        # pricing engine already computed. The drafter weaves this into the reply.
        "price_summary": {"type": "string"},
        # The security deposit to state on the quotation/PDF. Null keeps the planner's value (or 0).
        "security_deposit": {"type": ["number", "null"]},
        "notes": {"type": "string"},
    },
    "required": ["price_summary"],
}


@dataclass
class PlannerRunResult:
    status: str
    run_id: int | None = None
    generated_text: str | None = None
    formatted_text: str | None = None
    template_id: int | None = None
    checker_passed: bool = False
    checker_feedback: str | None = None
    escalation_reason: str | None = None
    attempts: int = 0
    # True only when the checker approved the draft; the auto pipeline refuses to send otherwise.
    auto_send_allowed: bool = False
    # Set only when the planner instructed a channel different from the one it was invoked with
    # (and the run was allowed to honour it). None means "keep the caller's channel/target". The
    # target ids are the concrete email thread / WhatsApp endpoint resolved for the new channel.
    chosen_channel: str | None = None
    chosen_email_thread_id: int | None = None
    chosen_whatsapp_endpoint_id: int | None = None
    # Set when the sales-manager agent produced a PDF quotation for this reply. The caller persists
    # the bytes as a CommunicationAttachment and attaches it to the outgoing message.
    quotation_pdf_bytes: bytes | None = None
    quotation_pdf_filename: str | None = None
    quotation_web_url: str | None = None


@dataclass
class _RunRecorder:
    """Accumulates steps and totals for one run, so the loop body stays free of bookkeeping."""

    run: AiAgentRun
    db: Session
    started: float = field(default_factory=time.monotonic)
    _index: int = 0

    def record(
        self,
        stage: str,
        *,
        prompt: str,
        result: gemini_client.GenerationResult | None = None,
        error: str | None = None,
        model: str | None = None,
    ) -> None:
        step = AiAgentRunStep(
            run_id=self.run.id,
            step_index=self._index,
            stage=stage,
            model=result.model if result is not None else model,
            prompt=prompt,
            response=result.text if result is not None else None,
            parsed=result.parsed if result is not None else None,
            prompt_tokens=result.prompt_tokens if result is not None else None,
            output_tokens=result.output_tokens if result is not None else None,
            latency_ms=result.latency_ms if result is not None else None,
            error=error,
        )
        self.db.add(step)
        self._index += 1
        if result is not None:
            self.run.total_prompt_tokens += result.prompt_tokens or 0
            self.run.total_output_tokens += result.output_tokens or 0

    def finish(self, status: str, **fields) -> None:
        self.run.status = status
        self.run.duration_ms = int((time.monotonic() - self.started) * 1000)
        for key, value in fields.items():
            setattr(self.run, key, value)


class _NullRecorder:
    def record(
        self,
        stage: str,
        *,
        prompt: str,
        result: gemini_client.GenerationResult | None = None,
        error: str | None = None,
        model: str | None = None,
    ) -> None:
        return None


def resolve_profile(db: Session, role: str, pinned_id: int | None) -> AiAgentProfile | None:
    """A tenant's pinned profile if it is still usable, otherwise the role's active default."""
    if pinned_id is not None:
        pinned = (
            db.query(AiAgentProfile)
            .filter(AiAgentProfile.id == pinned_id, AiAgentProfile.role == role, AiAgentProfile.is_active.is_(True))
            .first()
        )
        if pinned is not None:
            return pinned
    return (
        db.query(AiAgentProfile)
        .filter(
            AiAgentProfile.role == role,
            AiAgentProfile.is_default.is_(True),
            AiAgentProfile.is_active.is_(True),
        )
        .first()
    )


def _generation_kwargs(profile: AiAgentProfile | None, *, is_redo: bool = False) -> dict[str, str | float | int | None]:
    if profile is None:
        return {"model": None, "temperature": None, "max_output_tokens": None}
    return {
        "model": profile.redo_model if is_redo and profile.redo_model is not None else profile.model,
        "temperature": profile.redo_temperature if is_redo and profile.redo_temperature is not None else profile.temperature,
        "max_output_tokens": (
            profile.redo_max_output_tokens
            if is_redo and profile.redo_max_output_tokens is not None
            else profile.max_output_tokens
        ),
    }


def format_generated_draft(db: Session, tenant: Tenant, channel: str, draft: str) -> str | None:
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    if ai_settings is None or not ai_settings.formatter_enabled:
        return None
    formatter_profile = resolve_profile(db, FORMATTER_ROLE, ai_settings.formatter_profile_id if ai_settings else None)
    if formatter_profile is None:
        return None
    return _run_formatter(
        db,
        recorder=_NullRecorder(),
        tenant=tenant,
        channel=channel,
        draft=draft,
        formatter_profile=formatter_profile,
    )


def resolve_drafter_context(db: Session, pinned_id: int | None) -> tuple[dict[str, str], str | None]:
    """The prompt scaffolding and standing instructions the drafter should use for this tenant.

    Shared by the planner loop and the two "Draft with AI" endpoints so the payload preview keeps
    matching what is actually sent. With no drafter profile configured this returns the built-in
    scaffolding and no instructions, i.e. the behaviour from before profiles carried prompt text.
    """
    profile = resolve_profile(db, DRAFTER_ROLE, pinned_id)
    blocks = ai_prompt_blocks.resolve_blocks(profile, DRAFTER_ROLE)
    instructions = resolve_datetime_placeholders((profile.instructions or "").strip()) if profile is not None else ""
    return blocks, instructions or None


def tokens_spent_today(db: Session) -> int:
    """Total planner/checker tokens billed since midnight UTC, across every tenant."""
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    totals = (
        db.query(
            func.coalesce(func.sum(AiAgentRun.total_prompt_tokens), 0),
            func.coalesce(func.sum(AiAgentRun.total_output_tokens), 0),
        )
        .filter(AiAgentRun.created_at >= midnight)
        .first()
    )
    return int(totals[0] or 0) + int(totals[1] or 0)


def _daily_cap(db: Session, profiles: list[AiAgentProfile | None]) -> int | None:
    """The tightest cap in force: the global admin one and any the profiles impose."""
    caps = [profile.daily_token_cap for profile in profiles if profile is not None and profile.daily_token_cap]
    settings = db.query(AdminSettings).first()
    if settings is not None and settings.ai_daily_token_cap:
        caps.append(int(settings.ai_daily_token_cap))
    return min(caps) if caps else None


def _matched_keywords(profile: AiAgentProfile, text: str) -> list[str]:
    haystack = (text or "").lower()
    keywords = profile.escalate_keywords or []
    return [str(word) for word in keywords if str(word).strip() and str(word).strip().lower() in haystack]


def latest_inbound_text(db: Session, tenant_id: int, channel: str) -> str | None:
    """The message the planner is reacting to, so guardrails and prompts have something concrete."""
    if channel == "email":
        message = (
            db.query(ConversationMessage)
            .join(TenantConversationLink, TenantConversationLink.conversation_id == ConversationMessage.conversation_id)
            .filter(
                TenantConversationLink.tenant_id == tenant_id,
                TenantConversationLink.unlinked_at.is_(None),
                TenantConversationLink.is_visible.is_(True),
                ConversationMessage.direction == "inbound",
            )
            .order_by(ConversationMessage.sent_at.desc(), ConversationMessage.id.desc())
            .first()
        )
        return (message.body or "").strip() if message is not None else None

    messages = [
        message
        for message in load_tenant_whatsapp_messages(db, tenant_id)
        if message.direction == "inbound"
    ]
    return (messages[-1].message or "").strip() if messages else None


def latest_message_text(db: Session, tenant_id: int, channel: str) -> str | None:
    """Direction-agnostic sibling of latest_inbound_text, for triggers that fire on outbound
    messages too (brain_writer, action_writer) - a tenant whose very first message was outbound
    must still get a focus message rather than silently no-op.
    """
    if channel == "email":
        message = (
            db.query(ConversationMessage)
            .join(TenantConversationLink, TenantConversationLink.conversation_id == ConversationMessage.conversation_id)
            .filter(
                TenantConversationLink.tenant_id == tenant_id,
                TenantConversationLink.unlinked_at.is_(None),
                TenantConversationLink.is_visible.is_(True),
            )
            .order_by(ConversationMessage.sent_at.desc(), ConversationMessage.id.desc())
            .first()
        )
        return (message.body or "").strip() if message is not None else None

    messages = load_tenant_whatsapp_messages(db, tenant_id)
    return (messages[-1].message or "").strip() if messages else None


def _resolve_history_channels(profile: AiAgentProfile, channel: str) -> str:
    """"inbound" means "whichever channel this message arrived on"; everything else is literal."""
    configured = (profile.history_channels or "both").strip()
    if configured == "inbound":
        return channel if channel in ("email", "whatsapp") else "both"
    return configured if configured in ("both", "email", "whatsapp") else "both"


def _build_context_blocks(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    channel: str,
    inbound_text: str | None,
    blocks: dict[str, str],
) -> list[str]:
    """The shared context every agent gets, sized by its own profile's budget."""
    parts: list[str] = []
    limit = max(0, int(profile.history_limit or 0))
    if limit:
        parts.append(
            ai_reply_service._build_history_context(
                db,
                tenant,
                limit,
                channels=_resolve_history_channels(profile, channel),
                lookback_days=profile.history_lookback_days,
                blocks=blocks,
            )
        )
    if profile.include_beds24:
        parts.append(ai_reply_service._build_beds24_context(tenant, blocks))
    if profile.include_payments:
        parts.append(ai_reply_service._build_payments_context(db, tenant, blocks))
    if profile.include_notes:
        parts.append(ai_reply_service._build_notes_context(tenant, blocks))
    parts.append(ai_reply_service._build_action_items_context(db, tenant, blocks))
    if profile.include_availability:
        parts.append(ai_reply_service._build_availability_context(db, blocks))
    if profile.include_tenant_brain:
        from app.services import memory_qa_service

        parts.append(memory_qa_service._fields_block(db, tenant.id, blocks))
        parts.append(memory_qa_service._entries_block(db, tenant.id, blocks))
    if inbound_text:
        parts.append(ai_prompt_blocks.join(blocks["ctx_inbound"], inbound_text))
    return parts


def _template_catalogue(db: Session, tenant_id: int) -> tuple[str, set[int]]:
    """The templates the planner may choose from, restricted to what this tenant has available.

    Returns the rendered catalogue and the allowed id set, so a hallucinated id can be rejected
    rather than silently drafting from a template the operator never enabled for this tenant.
    """
    from app.models.tenant_ai_template_link import TenantAiTemplateLink

    linked_ids = {
        row[0]
        for row in db.query(TenantAiTemplateLink.template_id)
        .filter(TenantAiTemplateLink.tenant_id == tenant_id)
        .all()
    }
    query = db.query(AiReplyTemplate).order_by(AiReplyTemplate.name)
    templates = [template for template in query.all() if not linked_ids or template.id in linked_ids]
    if not templates:
        return "No templates are available for this tenant.", set()

    lines = [
        f"- id={template.id} | {template.name} | {(template.description or '').strip() or 'No description provided.'}"
        for template in templates
    ]
    return "\n".join(lines), {template.id for template in templates}


def _language_directive(profile: AiAgentProfile, blocks: dict[str, str]) -> str | None:
    """The language rule, or None when this profile does not enforce one.

    The `## Language` heading lives inside the block text itself, so clearing the block removes
    the heading too rather than leaving a bare heading behind.
    """
    if not profile.match_inbound_language:
        return None
    return (blocks["language"] or "").strip() or None


def _build_planner_prompt(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    catalogue: str,
    channel: str,
    inbound_text: str | None,
    operator_note: str | None,
    attachment_count: int = 0,
    attachment_names: str = "",
) -> str:
    """Assemble the planner prompt from this profile's editable blocks.

    Every fixed string here comes from `ai_prompt_blocks`, so an operator reading the run log can
    change any of it. A block whose text is empty contributes nothing: for the standalone blocks
    that means they vanish, and for the framed ones the live data is emitted on its own.
    """
    text = ai_prompt_blocks.resolve_blocks(profile, PLANNER_ROLE)
    parts: list[str] = []

    preamble = (text["preamble"] or "").strip()
    if preamble:
        parts.append(preamble)

    instructions = resolve_datetime_placeholders((profile.instructions or "").strip())
    if instructions:
        parts.append(ai_prompt_blocks.join(text["instructions_header"], instructions))

    directive = _language_directive(profile, text)
    if directive:
        parts.append(directive)

    parts.append(ai_prompt_blocks.join(text["catalogue"], catalogue))

    if profile.include_brain_index:
        parts.append(ai_prompt_blocks.join(text["brain_index"], brain_service.build_brain_index(db)))
    pinned_sections = [str(path).strip() for path in (profile.always_include_brain_sections or []) if str(path).strip()]
    if pinned_sections:
        rendered = brain_service.render_paths(db, pinned_sections)
        if rendered.text.strip():
            parts.append(ai_prompt_blocks.join(text["brain_sections"], rendered.text.strip()))
        if rendered.missing_paths:
            logger.warning(
                "Planner profile requested missing brain sections tenant_id=%s missing=%s",
                tenant.id,
                ", ".join(rendered.missing_paths),
            )

    parts += _build_context_blocks(db, tenant, profile, channel=channel, inbound_text=inbound_text, blocks=text)

    note = (operator_note or "").strip()
    if note:
        parts.append(ai_prompt_blocks.join(text["operator_note"], note))

    if attachment_count:
        attachment_block = (text["attachment_instruction"] or "").strip()
        if attachment_block:
            parts.append(ai_prompt_blocks.fill(attachment_block, count=attachment_count, names=attachment_names))

    output = (text["output"] or "").strip()
    if output:
        parts.append(output)
    return "\n\n".join(part for part in parts if part.strip())


def _build_checker_prompt(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    channel: str,
    draft: str,
    inbound_text: str | None,
    plan_instructions: str,
    knowledge: str,
    brain_index: str,
    template: AiReplyTemplate | None = None,
    attachment_count: int = 0,
    attachment_names: str = "",
) -> str:
    """Assemble the checker prompt from this profile's editable blocks. See _build_planner_prompt."""
    text = ai_prompt_blocks.resolve_blocks(profile, CHECKER_ROLE)
    parts: list[str] = []

    preamble = (text["preamble"] or "").strip()
    if preamble:
        parts.append(preamble)

    instructions = resolve_datetime_placeholders((profile.instructions or "").strip())
    if instructions:
        parts.append(ai_prompt_blocks.join(text["instructions_header"], instructions))

    directive = _language_directive(profile, text)
    if directive:
        parts.append(directive)

    if plan_instructions.strip():
        parts.append(ai_prompt_blocks.join(text["plan_instructions"], plan_instructions.strip()))

    if profile.include_brain_index:
        # The resolved sections the draft was actually written from, so the checker reviews
        # against the same policy text the drafter saw, plus the cheap title/path index so it
        # can name anything else it needs - full text is only ever resolved for named paths.
        if knowledge.strip():
            parts.append(ai_prompt_blocks.join(text["knowledge"], knowledge.strip()))
        if brain_index.strip():
            parts.append(ai_prompt_blocks.join(text["brain_index"], brain_index.strip()))

    if template is not None:
        # Rendered with the drafter's own builders so the checker reviews against exactly the
        # text the drafter was given, not a paraphrase of it. `template.description` is
        # deliberately excluded: it describes when to *pick* this template and is planner-only.
        template_parts = [f"Template: {template.name}"]
        guidelines = ai_reply_service._build_guidelines_content(db, template, tenant)
        if guidelines.strip():
            template_parts.append(guidelines.strip())
        sections = ai_reply_service._build_sections_prompt(db, template, tenant)
        if sections.strip():
            template_parts.append(sections.strip())
        if len(template_parts) > 1:
            parts.append(ai_prompt_blocks.join(text["template"], "\n\n".join(template_parts)))

    parts += _build_context_blocks(db, tenant, profile, channel=channel, inbound_text=inbound_text, blocks=text)
    parts.append(ai_prompt_blocks.join(text["draft"], draft))

    if attachment_count:
        attachment_block = (text["attachment_instruction"] or "").strip()
        if attachment_block:
            parts.append(ai_prompt_blocks.fill(attachment_block, count=attachment_count, names=attachment_names))

    output = (text["output"] or "").strip()
    if output:
        parts.append(output)
    return "\n\n".join(part for part in parts if part.strip())


def _build_formatter_prompt(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    channel: str,
    draft: str,
) -> str:
    """Format an approved draft into channel-specific output without changing its meaning."""
    text = ai_prompt_blocks.resolve_blocks(profile, FORMATTER_ROLE)
    parts: list[str] = []

    preamble = (text["preamble"] or "").strip()
    if preamble:
        parts.append(preamble)

    instructions = resolve_datetime_placeholders((profile.instructions or "").strip())
    if instructions:
        parts.append(ai_prompt_blocks.join(text["instructions_header"], instructions))

    if channel == "email":
        channel_block = (text["email"] or "").strip()
    else:
        channel_block = (text["whatsapp"] or "").strip()
    if channel_block:
        parts.append(channel_block)

    parts.append(ai_prompt_blocks.join(text["draft"], draft))

    output = (text["output"] or "").strip()
    if output:
        parts.append(output)
    return "\n\n".join(part for part in parts if part.strip())


def _run_formatter(
    db: Session,
    *,
    recorder: _RunRecorder,
    tenant: Tenant,
    channel: str,
    draft: str,
    formatter_profile: AiAgentProfile,
    is_redo: bool = False,
) -> str | None:
    formatter_prompt = _build_formatter_prompt(db, tenant, formatter_profile, channel=channel, draft=draft)
    try:
        formatter_result = gemini_client.generate(
            formatter_prompt,
            **_generation_kwargs(formatter_profile, is_redo=is_redo),
            response_schema=FORMATTER_SCHEMA,
        )
    except Exception as exc:
        recorder.record("formatter", prompt=formatter_prompt, error=str(exc), model=_generation_kwargs(formatter_profile, is_redo=is_redo)["model"])
        logger.exception("Formatter failed tenant_id=%s channel=%s", tenant.id, channel)
        return None

    recorder.record("formatter", prompt=formatter_prompt, result=formatter_result)
    parsed = formatter_result.parsed or {}
    formatted_text = str(parsed.get("formatted_text") or "").strip()
    if channel == "whatsapp" and formatted_text and formatter_output_looks_like_html(formatted_text):
        logger.warning(
            "WhatsApp formatter output looks like HTML; falling back to generated_text tenant_id=%s",
            tenant.id,
        )
        return draft
    return formatted_text or None


def formatter_output_looks_like_html(value: str | None) -> bool:
    return bool(value and _HTML_TAG_RE.search(value))


@dataclass
class SalesManagerResult:
    # The factual price summary the drafter should weave into the reply (already grounded on the
    # pricing engine's numbers), plus a note the drafter should include and, when a PDF was made,
    # its bytes/filename/link so the caller can attach it and reference it.
    ok: bool
    drafter_note: str = ""
    escalation_reason: str | None = None
    pdf_bytes: bytes | None = None
    pdf_filename: str | None = None
    pdf_web_url: str | None = None


_SALES_SCOPES = {"price", "pdf", "both"}


def _normalize_sales_scope(value: object) -> str:
    scope = str(value or "").strip().lower()
    return scope if scope in _SALES_SCOPES else "price"


def _build_sales_manager_prompt(
    profile: AiAgentProfile,
    *,
    params: dict,
    charges_text: str,
    inbound_text: str | None,
) -> str:
    text = ai_prompt_blocks.resolve_blocks(profile, SALES_MANAGER_ROLE)
    parts: list[str] = []

    preamble = (text["preamble"] or "").strip()
    if preamble:
        parts.append(preamble)

    instructions = resolve_datetime_placeholders((profile.instructions or "").strip())
    if instructions:
        parts.append(ai_prompt_blocks.join(text["instructions_header"], instructions))

    request_lines = "\n".join(
        f"- {key}: {value}" for key, value in params.items() if value not in (None, "")
    )
    parts.append(ai_prompt_blocks.join(text["request"], request_lines))
    parts.append(ai_prompt_blocks.join(text["charges"], charges_text))
    if inbound_text:
        parts.append(ai_prompt_blocks.join(text["inbound"], inbound_text.strip()))

    output = (text["output"] or "").strip()
    if output:
        parts.append(output)
    return "\n\n".join(part for part in parts if part.strip())


def _run_sales_manager(
    db: Session,
    *,
    recorder,
    tenant: Tenant,
    sales_profile: AiAgentProfile,
    sales_request: dict,
    inbound_text: str | None,
    user_id: int | None,
    is_redo: bool,
) -> SalesManagerResult:
    """Price and, when asked, render a PDF quotation, returning what the drafter needs.

    The pricing figures come from the quotation engine (never the model); the model only turns
    them into a guest-facing summary. Any failure escalates rather than sending a reply with a
    made-up or missing quote.
    """
    scope = _normalize_sales_scope(sales_request.get("scope"))
    params = sales_manager_service.resolve_quote_params(tenant, sales_request)

    try:
        quote = sales_manager_service.compute_charges(tenant, params, issued_by_user_id=user_id)
    except sales_manager_service.SalesManagerError as exc:
        recorder.record("sales_manager", prompt=f"build-charges {params}", error=str(exc))
        logger.warning("Sales manager pricing failed tenant_id=%s: %s", tenant.id, exc)
        return SalesManagerResult(ok=False, escalation_reason="sales_manager_pricing_failed")

    charges_text = sales_manager_service.render_charges_text(quote)
    prompt = _build_sales_manager_prompt(
        sales_profile, params=params, charges_text=charges_text, inbound_text=inbound_text
    )
    try:
        result = gemini_client.generate(
            prompt,
            **_generation_kwargs(sales_profile, is_redo=is_redo),
            response_schema=SALES_MANAGER_SCHEMA,
        )
    except gemini_client.GeminiClientError as exc:
        recorder.record("sales_manager", prompt=prompt, error=str(exc), model=_generation_kwargs(sales_profile, is_redo=is_redo)["model"])
        logger.warning("Sales manager model call failed tenant_id=%s: %s", tenant.id, exc)
        return SalesManagerResult(ok=False, escalation_reason="sales_manager_model_failed")

    recorder.record("sales_manager", prompt=prompt, result=result)
    parsed = result.parsed or {}
    price_summary = str(parsed.get("price_summary") or "").strip() or charges_text
    requested_deposit = sales_request.get("security_deposit")
    deposit = parsed.get("security_deposit")
    if deposit is None:
        deposit = requested_deposit if requested_deposit is not None else 0
    notes = str(parsed.get("notes") or "").strip()

    drafter_note_parts = [
        "The sales manager priced this stay. Use these exact figures in the reply:",
        price_summary,
    ]
    if notes:
        drafter_note_parts.append(f"Notes: {notes}")

    sales_result = SalesManagerResult(ok=True)
    if scope in ("pdf", "both"):
        invoice_items = sales_manager_service.charges_to_invoice_items(quote.charges)
        try:
            pdf = sales_manager_service.generate_quotation_pdf(
                tenant,
                params,
                invoice_items,
                security_deposit=float(deposit or 0),
                issued_by_user_id=user_id,
            )
        except sales_manager_service.SalesManagerError as exc:
            recorder.record("sales_manager", prompt="generate-pdf", error=str(exc))
            logger.warning("Sales manager PDF generation failed tenant_id=%s: %s", tenant.id, exc)
            return SalesManagerResult(ok=False, escalation_reason="sales_manager_pdf_failed")
        sales_result.pdf_bytes = pdf.content
        sales_result.pdf_filename = pdf.filename
        sales_result.pdf_web_url = pdf.web_url
        drafter_note_parts.append(
            "A PDF quotation is attached to this message"
            + (f" (also filed at {pdf.web_url})" if pdf.web_url else "")
            + "; refer to it in the reply."
        )

    sales_result.drafter_note = "\n".join(drafter_note_parts)
    return sales_result


def run_planner_loop(
    db: Session,
    *,
    tenant: Tenant,
    channel: str,
    mode: str,
    inbound_text: str | None = None,
    operator_note: str | None = None,
    attachments: list[attachment_service.OutboundAttachment] | None = None,
    user_id: int | None = None,
    is_redo: bool = False,
    respect_planner_channel: bool = False,
    outbound_email_thread_id: int | None = None,
    outbound_whatsapp_endpoint_id: int | None = None,
) -> PlannerRunResult:
    """Plan, draft and review a reply. Adds an AiAgentRun to the session but does not commit."""
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    planner_profile = resolve_profile(db, PLANNER_ROLE, ai_settings.planner_profile_id if ai_settings else None)
    checker_profile = resolve_profile(db, CHECKER_ROLE, ai_settings.checker_profile_id if ai_settings else None)
    drafter_profile = resolve_profile(db, DRAFTER_ROLE, ai_settings.drafter_profile_id if ai_settings else None)
    drafter_blocks, drafter_instructions = resolve_drafter_context(
        db, ai_settings.drafter_profile_id if ai_settings else None
    )

    run = AiAgentRun(
        tenant_id=tenant.id,
        channel=channel,
        mode=mode,
        status=STATUS_FAILED,
        planner_profile_id=planner_profile.id if planner_profile else None,
        checker_profile_id=checker_profile.id if checker_profile else None,
        created_by_user_id=user_id,
    )
    db.add(run)
    # Flush so run.id exists for the step rows; the caller still owns the commit.
    db.flush()
    recorder = _RunRecorder(run=run, db=db)

    if planner_profile is None:
        recorder.finish(STATUS_FAILED, escalation_reason="no_planner_profile")
        return PlannerRunResult(status=STATUS_FAILED, run_id=run.id, escalation_reason="no_planner_profile")

    # Guardrail first: a message about refunds or lawyers should never reach the model at all.
    matched = _matched_keywords(planner_profile, inbound_text or "")
    if matched:
        reason = f"keyword:{matched[0]}"
        recorder.finish(STATUS_ESCALATED, escalation_reason=reason)
        return PlannerRunResult(status=STATUS_ESCALATED, run_id=run.id, escalation_reason=reason)

    cap = _daily_cap(db, [planner_profile, checker_profile])
    if cap is not None and tokens_spent_today(db) >= cap:
        recorder.finish(STATUS_ESCALATED, escalation_reason="token_cap")
        return PlannerRunResult(status=STATUS_ESCALATED, run_id=run.id, escalation_reason="token_cap")

    file_parts: list[gemini_client.FilePart] = []
    # attachment_count/attachment_names feed the editable "attachment_instruction" prompt block
    # (ai_prompt_blocks.py, one per role) via each builder below - not just passed as inline file
    # parts, so every stage is explicitly told the attachments exist and is expected to use them.
    # Since _RunRecorder.record() logs exactly the prompt string that was sent, the resolved,
    # filled-in instruction also lands directly in the run's audit trail with no separate
    # bookkeeping, and an operator can reword or clear the instruction per role like any other
    # prompt block.
    attachment_count = 0
    attachment_names = ""
    if attachments:
        selection = attachment_service.select_for_multimodal(attachments)
        if selection.eligible:
            file_parts = [
                gemini_client.FilePart(data=att.content, mime_type=att.mime_type)
                for att in selection.eligible
            ]
            attachment_count = len(selection.eligible)
            attachment_names = ", ".join(f"{att.filename} ({att.mime_type})" for att in selection.eligible)
            logger.info(
                "Planner run tenant_id=%s forwarding attachment(s) to AI: %s",
                tenant.id, attachment_names,
            )
        if selection.skipped:
            logger.info(
                "Planner run tenant_id=%s skipped attachment(s) for AI: %s",
                tenant.id, "; ".join(selection.skipped),
            )

    catalogue, allowed_template_ids = _template_catalogue(db, tenant.id)
    planner_prompt = _build_planner_prompt(
        db,
        tenant,
        planner_profile,
        catalogue=catalogue,
        channel=channel,
        inbound_text=inbound_text,
        operator_note=operator_note,
        attachment_count=attachment_count,
        attachment_names=attachment_names,
    )
    try:
        planner_result = gemini_client.generate(
            planner_prompt,
            **_generation_kwargs(planner_profile, is_redo=is_redo),
            response_schema=PLANNER_SCHEMA,
            file_parts=file_parts or None,
        )
    except gemini_client.GeminiClientError as exc:
        recorder.record("planner", prompt=planner_prompt, error=str(exc), model=_generation_kwargs(planner_profile, is_redo=is_redo)["model"])
        recorder.finish(STATUS_FAILED, escalation_reason="planner_error")
        return PlannerRunResult(status=STATUS_FAILED, run_id=run.id, escalation_reason="planner_error")

    recorder.record("planner", prompt=planner_prompt, result=planner_result)
    plan = planner_result.parsed or {}

    if not plan.get("should_reply", False):
        recorder.finish(STATUS_SKIPPED, escalation_reason="planner_declined")
        return PlannerRunResult(status=STATUS_SKIPPED, run_id=run.id, escalation_reason="planner_declined")

    # Honour the planner's channel choice on automated paths only. Manual/redo runs pass
    # respect_planner_channel=False, so a person's explicit channel pick is never overridden.
    # A choice the tenant can't receive on (no linked WhatsApp chat, no email thread, ambiguous
    # WhatsApp) parks the reply for a human instead of silently switching channels. Everything
    # downstream (drafter/checker/formatter) then styles the reply for the chosen channel.
    chosen_channel: str | None = None
    chosen_email_thread_id: int | None = None
    chosen_whatsapp_endpoint_id: int | None = None
    if respect_planner_channel:
        requested = outbound_target_resolver.normalize_channel(plan.get("channel"))
        if requested and requested != channel:
            target = outbound_target_resolver.resolve_outbound_target(
                db,
                tenant,
                requested,
                known_email_thread_id=outbound_email_thread_id,
                known_whatsapp_endpoint_id=outbound_whatsapp_endpoint_id,
            )
            if not target.reachable:
                recorder.finish(STATUS_ESCALATED, escalation_reason="channel_unavailable")
                return PlannerRunResult(
                    status=STATUS_ESCALATED, run_id=run.id, escalation_reason="channel_unavailable"
                )
            channel = requested
            run.channel = requested
            chosen_channel = requested
            chosen_email_thread_id = target.email_thread_id
            chosen_whatsapp_endpoint_id = target.whatsapp_endpoint_id

    template_id = plan.get("template_id")
    confidence = float(plan.get("confidence") or 0.0)
    no_match = template_id is None or template_id not in allowed_template_ids
    if no_match or confidence < float(planner_profile.min_confidence or 0.0):
        reason = "no_template_match" if no_match else "low_confidence"
        # `skip` produces nothing at all; `escalate` parks the conversation for a human.
        status = STATUS_SKIPPED if planner_profile.on_no_template_match == "skip" else STATUS_ESCALATED
        recorder.finish(status, escalation_reason=reason)
        return PlannerRunResult(status=status, run_id=run.id, escalation_reason=reason)

    template = db.query(AiReplyTemplate).filter(AiReplyTemplate.id == template_id).first()
    if template is None:
        recorder.finish(STATUS_ESCALATED, escalation_reason="no_template_match")
        return PlannerRunResult(status=STATUS_ESCALATED, run_id=run.id, escalation_reason="no_template_match")

    extra_sections = [str(path) for path in (plan.get("extra_brain_sections") or [])]
    plan_instructions = str(plan.get("extra_instructions") or "").strip()
    # The operator's own words lead, so a manual run never has its intent overwritten by the plan.
    drafter_instruction = "\n\n".join(part for part in [(operator_note or "").strip(), plan_instructions] if part)

    # Sales manager: runs between planner and drafter, but only when the planner asked for a quote.
    # It prices the stay (and optionally renders+files a PDF) and hands the drafter the exact
    # figures. A failure escalates rather than drafting a reply with a missing/made-up quote.
    quotation_pdf_bytes: bytes | None = None
    quotation_pdf_filename: str | None = None
    quotation_web_url: str | None = None
    sales_request = plan.get("sales_request") or {}
    if isinstance(sales_request, dict) and sales_request.get("needed"):
        sales_profile = resolve_profile(
            db, SALES_MANAGER_ROLE, ai_settings.sales_manager_profile_id if ai_settings else None
        )
        if sales_profile is None:
            recorder.finish(STATUS_ESCALATED, escalation_reason="sales_manager_unavailable", final_template_id=template.id)
            return PlannerRunResult(
                status=STATUS_ESCALATED, run_id=run.id, template_id=template.id,
                escalation_reason="sales_manager_unavailable",
            )
        sales_result = _run_sales_manager(
            db,
            recorder=recorder,
            tenant=tenant,
            sales_profile=sales_profile,
            sales_request=sales_request,
            inbound_text=inbound_text,
            user_id=user_id,
            is_redo=is_redo,
        )
        if not sales_result.ok:
            recorder.finish(STATUS_ESCALATED, escalation_reason=sales_result.escalation_reason, final_template_id=template.id)
            return PlannerRunResult(
                status=STATUS_ESCALATED, run_id=run.id, template_id=template.id,
                escalation_reason=sales_result.escalation_reason,
            )
        # The sales manager's factual figures lead the drafter's instruction.
        drafter_instruction = "\n\n".join(part for part in [drafter_instruction, sales_result.drafter_note] if part)
        quotation_pdf_bytes = sales_result.pdf_bytes
        quotation_pdf_filename = sales_result.pdf_filename
        quotation_web_url = sales_result.pdf_web_url

    # Titles/paths only, no section bodies - cheap enough to give the checker every run so it
    # can name a missing section instead of guessing. Computed once; doesn't change mid-run.
    brain_index_text = (
        brain_service.build_brain_index(db)
        if checker_profile is not None and checker_profile.include_brain_index
        else ""
    )
    knowledge_content = ""
    resolved_for: tuple[str, ...] | None = None

    # One initial draft plus the configured number of redrafts. `or` is deliberately avoided:
    # max_redraft_attempts=0 means "no redrafts", not "unset".
    redrafts = checker_profile.max_redraft_attempts if checker_profile is not None else None
    max_attempts = (int(redrafts) + 1) if redrafts is not None else 1
    feedback: str | None = None
    rejected_draft: str | None = None
    draft_text = ""
    checker_passed = False

    for attempt in range(1, max_attempts + 1):
        run.attempts = attempt
        # Re-resolve only when the checker (or the planner) has added a path since the last
        # attempt - otherwise every redraft would re-render the same sections from the DB.
        if resolved_for != tuple(extra_sections):
            knowledge_content = ai_reply_service._build_knowledge_base(db, template, tenant, extra_sections)
            resolved_for = tuple(extra_sections)
        draft_prompt = ai_reply_service.assemble_prompt(
            db,
            tenant=tenant,
            template=template,
            channel=channel,
            rough_draft=drafter_instruction or None,
            inbound_text=inbound_text,
            extra_brain_section_paths=extra_sections,
            knowledge_content=knowledge_content,
            previous_draft=rejected_draft,
            reviewer_feedback=feedback,
            blocks=drafter_blocks,
            agent_instructions=drafter_instructions,
            attachment_count=attachment_count,
            attachment_names=attachment_names,
        )
        try:
            draft_result = gemini_client.generate(
                draft_prompt,
                **_generation_kwargs(drafter_profile, is_redo=is_redo),
                file_parts=file_parts or None,
            )
        except gemini_client.GeminiClientError as exc:
            recorder.record("drafter", prompt=draft_prompt, error=str(exc))
            recorder.finish(STATUS_FAILED, escalation_reason="drafter_error", final_template_id=template.id)
            return PlannerRunResult(
                status=STATUS_FAILED, run_id=run.id, template_id=template.id, escalation_reason="drafter_error"
            )
        recorder.record("drafter", prompt=draft_prompt, result=draft_result)
        draft_text = draft_result.text

        if checker_profile is None:
            # Without a checker there is nothing to approve the draft, so it is handed over as
            # unreviewed rather than being treated as passed.
            checker_passed = False
            break

        checker_prompt = _build_checker_prompt(
            db,
            tenant,
            checker_profile,
            channel=channel,
            draft=draft_text,
            inbound_text=inbound_text,
            plan_instructions=drafter_instruction,
            knowledge=knowledge_content,
            brain_index=brain_index_text,
            template=template,
            attachment_count=attachment_count,
            attachment_names=attachment_names,
        )
        try:
            checker_result = gemini_client.generate(
                checker_prompt,
                **_generation_kwargs(checker_profile, is_redo=is_redo),
                response_schema=CHECKER_SCHEMA,
                file_parts=file_parts or None,
            )
        except gemini_client.GeminiClientError as exc:
            recorder.record("checker", prompt=checker_prompt, error=str(exc), model=_generation_kwargs(checker_profile, is_redo=is_redo)["model"])
            recorder.finish(
                STATUS_NEEDS_REVIEW,
                escalation_reason="checker_error",
                final_template_id=template.id,
                final_text=draft_text,
            )
            return PlannerRunResult(
                status=STATUS_NEEDS_REVIEW,
                run_id=run.id,
                generated_text=draft_text,
                template_id=template.id,
                escalation_reason="checker_error",
                attempts=attempt,
            )

        recorder.record("checker", prompt=checker_prompt, result=checker_result)
        verdict = checker_result.parsed or {}
        if verdict.get("passed"):
            checker_passed = True
            feedback = None
            rejected_draft = None
            break
        # A rejection may name sections it needed but didn't have; the next attempt's drafter
        # and checker prompts both pick these up via the resolved-set check above.
        for path in [str(p) for p in (verdict.get("extra_brain_sections") or [])]:
            if path and path not in extra_sections:
                extra_sections.append(path)
        feedback = str(verdict.get("feedback") or "").strip() or "The reviewer rejected the draft."
        issues = [str(issue).strip() for issue in (verdict.get("issues") or []) if str(issue).strip()]
        if issues:
            feedback += "\n\nSpecific issues:\n" + "\n".join(f"- {issue}" for issue in issues)
        # So the next drafting attempt is a rewrite of what it actually wrote, not a blind retry.
        rejected_draft = draft_text

    if checker_passed:
        formatter_profile = None
        formatted_text = None
        if ai_settings is not None and ai_settings.formatter_enabled:
            formatter_profile = resolve_profile(
                db,
                FORMATTER_ROLE,
                ai_settings.formatter_profile_id if ai_settings else None,
            )
        if formatter_profile is not None:
            formatted_text = _run_formatter(
                db,
                recorder=recorder,
                tenant=tenant,
                channel=channel,
                draft=draft_text,
                formatter_profile=formatter_profile,
                is_redo=is_redo,
            )
        recorder.finish(STATUS_COMPLETED, final_template_id=template.id, final_text=draft_text)
        return PlannerRunResult(
            status=STATUS_COMPLETED,
            run_id=run.id,
            generated_text=draft_text,
            formatted_text=formatted_text,
            template_id=template.id,
            checker_passed=True,
            attempts=run.attempts,
            auto_send_allowed=True,
            chosen_channel=chosen_channel,
            chosen_email_thread_id=chosen_email_thread_id,
            chosen_whatsapp_endpoint_id=chosen_whatsapp_endpoint_id,
            quotation_pdf_bytes=quotation_pdf_bytes,
            quotation_pdf_filename=quotation_pdf_filename,
            quotation_web_url=quotation_web_url,
        )

    # Attempts exhausted (or no checker configured): keep the last draft and park it for a human.
    block_auto_send = checker_profile.block_auto_send_on_fail if checker_profile is not None else True
    recorder.finish(
        STATUS_NEEDS_REVIEW,
        final_template_id=template.id,
        final_text=draft_text,
        checker_feedback=feedback,
        escalation_reason="checker_rejected" if checker_profile is not None else "no_checker_profile",
    )
    return PlannerRunResult(
        status=STATUS_NEEDS_REVIEW,
        run_id=run.id,
        generated_text=draft_text,
        formatted_text=None,
        template_id=template.id,
        checker_passed=False,
        checker_feedback=feedback,
        attempts=run.attempts,
        auto_send_allowed=not block_auto_send,
        chosen_channel=chosen_channel,
        chosen_email_thread_id=chosen_email_thread_id,
        chosen_whatsapp_endpoint_id=chosen_whatsapp_endpoint_id,
        quotation_pdf_bytes=quotation_pdf_bytes,
        quotation_pdf_filename=quotation_pdf_filename,
        quotation_web_url=quotation_web_url,
    )
