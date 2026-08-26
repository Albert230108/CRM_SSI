from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.action_item import ActionItem
from app.models.ai_reply_template import AiReplyTemplate
from app.models.finance import Finance as FinanceRecord
from app.models.gmail_integration import ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.services import ai_prompt_blocks, beds24_availability_service, brain_service, gemini_client
from app.services.email_template_service import resolve_template_text
from app.services.thread_timeline_service import ensure_utc as _ensure_utc, load_tenant_whatsapp_messages

_DEFAULT_HISTORY_LIMIT = 20


def _blocks(blocks: dict[str, str] | None) -> dict[str, str]:
    """Fall back to the drafter's built-in scaffolding when a caller passes nothing.

    The planner and checker resolve their own role's blocks and pass them in; the three
    drafter entry points pass the drafter profile's. A caller that passes None gets the
    original hardcoded wording, so nothing breaks if a new call site forgets.
    """
    return blocks if blocks is not None else ai_prompt_blocks.DEFAULTS_BY_ROLE[ai_prompt_blocks.DRAFTER_ROLE]


@dataclass(frozen=True)
class _HistoryEntry:
    timestamp: datetime
    sort_id: int
    text: str


def _resolve_text(db: Session, text: str, tenant: Tenant) -> str:
    """Expand `{{brain:...}}` references first, then tenant `{{placeholders}}`.

    Order matters: brain content is authored with tenant placeholders in it, so the brain has
    to be inlined before the tenant pass runs, otherwise those placeholders stay literal.
    """
    expanded = brain_service.resolve_brain_tokens(db, text).text
    return resolve_template_text(expanded, tenant)


def _build_guidelines_content(db: Session, template: AiReplyTemplate, tenant: Tenant) -> str:
    return _resolve_text(db, (template.guidelines or "").strip(), tenant).strip()


def _build_sections_prompt(db: Session, template: AiReplyTemplate, tenant: Tenant) -> str:
    sections = template.sections or []
    blocks: list[str] = []
    for section in sections:
        label = str(section.get("label") or "").strip()
        content = _resolve_text(db, str(section.get("content") or "").strip(), tenant).strip()
        if not content:
            continue
        blocks.append(f"## {label}\n{content}" if label else content)
    return "\n\n".join(blocks)


def _build_knowledge_base(
    db: Session,
    template: AiReplyTemplate,
    tenant: Tenant,
    extra_paths: list[str] | None,
) -> str:
    """Brain sections attached to the template, plus any the Planner asked for on top.

    The template's own attachments come first and win de-duplication, so a Planner suggestion
    can add knowledge but never reorder or displace what the template author pinned.
    """
    paths = [link.brain_section.path for link in template.brain_links if link.brain_section is not None]
    paths += list(extra_paths or [])
    if not paths:
        return ""
    rendered = brain_service.render_paths(db, paths).text
    return resolve_template_text(rendered, tenant).strip()


def _build_beds24_context(tenant: Tenant, blocks: dict[str, str] | None = None) -> str:
    lines = [
        f"Booking ID: {tenant.booking_id}",
        f"Guest name: {tenant.name or 'Unknown'}",
        f"Email: {tenant.email or 'Unknown'}",
        f"Phone: {tenant.phone or 'Unknown'}",
        f"Mobile: {tenant.mobile or 'Unknown'}",
        f"Property: {tenant.property_name or tenant.room_name or 'Unknown'}",
        f"Room: {tenant.room_name or 'Unknown'}",
        f"Check-in: {tenant.check_in or 'Unknown'}",
        f"Check-out: {tenant.check_out or 'Unknown'}",
        f"Adults / Children: {tenant.num_adults or 0} / {tenant.num_children or 0}",
        f"Booking status: {tenant.booking_status or 'Unknown'}",
    ]
    return ai_prompt_blocks.join(_blocks(blocks)["ctx_beds24"], "\n".join(lines))


def _build_availability_context(db: Session, blocks: dict[str, str] | None = None) -> str:
    """The cached, pre-parsed Beds24 availability summary - never the raw per-date JSON."""
    summary = beds24_availability_service.get_cached_summary(db)
    context_note = beds24_availability_service.get_context_note(db).strip()
    if context_note:
        summary = f"{summary}\n\n{context_note}"
    return ai_prompt_blocks.join(_blocks(blocks)["ctx_availability"], summary)


def _build_payments_context(db: Session, tenant: Tenant, blocks: dict[str, str] | None = None) -> str:
    records = (
        db.query(FinanceRecord)
        .filter(FinanceRecord.tenant_id == tenant.id)
        .order_by(FinanceRecord.created_at.asc(), FinanceRecord.id.asc())
        .all()
    )
    heading = _blocks(blocks)["ctx_payments"]
    if not records:
        return ai_prompt_blocks.join(heading, "No payment or charge records on file.")

    lines = [
        f"- {record.type}: {record.amount} {record.currency} — {record.description or 'no description'}"
        for record in records
    ]
    return ai_prompt_blocks.join(heading, "\n".join(lines))


def _load_email_history(db: Session, tenant_id: int, limit: int) -> list[_HistoryEntry]:
    """Most recent `limit` email messages across every linked thread of this tenant."""
    messages = (
        db.query(ConversationMessage)
        .join(TenantConversationLink, TenantConversationLink.conversation_id == ConversationMessage.conversation_id)
        .filter(
            TenantConversationLink.tenant_id == tenant_id,
            TenantConversationLink.unlinked_at.is_(None),
            TenantConversationLink.is_visible.is_(True),
        )
        .order_by(ConversationMessage.sent_at.desc(), ConversationMessage.id.desc())
        .limit(limit)
        .all()
    )
    entries: list[_HistoryEntry] = []
    for message in messages:
        sent_at = _ensure_utc(message.sent_at)
        subject = (message.subject or "").strip()
        prefix = f"[EMAIL {message.direction}] {sent_at.isoformat()}"
        text = f"{prefix} — {subject}: {message.body}" if subject else f"{prefix}: {message.body}"
        entries.append(_HistoryEntry(timestamp=sent_at, sort_id=int(message.id), text=text))
    return entries


def _load_whatsapp_history(db: Session, tenant_id: int, limit: int) -> list[_HistoryEntry]:
    """Most recent `limit` WhatsApp messages, filtered exactly like the tenant's UI timeline.

    Reuses the timeline loader so a tenant with an active manual chat link never feeds the model
    stray messages from a different chat on the same account - what the model sees is what the
    operator sees in the thread view.
    """
    messages = load_tenant_whatsapp_messages(db, tenant_id)[-limit:] if limit > 0 else []
    return [
        _HistoryEntry(
            timestamp=_ensure_utc(message.created_at),
            sort_id=int(message.id),
            text=f"[WHATSAPP {message.direction}] {_ensure_utc(message.created_at).isoformat()}: {message.message}",
        )
        for message in messages
    ]


def _build_notes_context(tenant: Tenant, blocks: dict[str, str] | None = None) -> str:
    heading = _blocks(blocks)["ctx_notes"]
    notes = (tenant.notes or "").strip()
    if not notes:
        return ai_prompt_blocks.join(heading, "No internal notes on file.")
    return ai_prompt_blocks.join(heading, notes)


def _render_action_item_line(item: ActionItem) -> str:
    bits = [f"[{item.status}]"]
    if item.priority:
        bits.append(f"({item.priority})")
    bits.append(item.title)
    if item.due_date:
        bits.append(f"- due {item.due_date.isoformat()}")
    tag_names = [link.tag.name for link in item.tag_links if link.tag]
    if tag_names:
        bits.append(f"[tags: {', '.join(tag_names)}]")
    return "- " + " ".join(bits)


def _build_action_items_context(db: Session, tenant: Tenant, blocks: dict[str, str] | None = None) -> str:
    from app.services import action_item_service

    heading = _blocks(blocks)["ctx_actions"]
    items = action_item_service.list_for_tenant(db, tenant.id)
    if not items:
        return ai_prompt_blocks.join(heading, "No action items on file.")
    lines = [_render_action_item_line(item) for item in items]
    return ai_prompt_blocks.join(heading, "\n".join(lines))


def _build_history_context(
    db: Session,
    tenant: Tenant,
    limit: int,
    *,
    channels: str = "both",
    lookback_days: int | None = None,
    blocks: dict[str, str] | None = None,
) -> str:
    """Last `limit` messages for this tenant, oldest first.

    History is channel-agnostic by default: a reply on one channel routinely depends on what was
    said on the other, so both email (every linked thread, not just the one being replied to) and
    WhatsApp are merged into a single chronological stream and only then truncated to `limit`.
    Each line carries its channel so the model can tell the two mediums apart. `channels` narrows
    that to one medium and `lookback_days` drops anything older, both for planner/checker profiles
    that deliberately want a tighter context budget.
    """
    entries: list[_HistoryEntry] = []
    if channels in ("both", "email"):
        entries += _load_email_history(db, tenant.id, limit)
    if channels in ("both", "whatsapp"):
        entries += _load_whatsapp_history(db, tenant.id, limit)

    if lookback_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        entries = [entry for entry in entries if entry.timestamp >= cutoff]

    entries.sort(key=lambda entry: (entry.timestamp, entry.sort_id))
    entries = entries[-limit:] if limit > 0 else []

    scope = {"both": "email and WhatsApp", "email": "email", "whatsapp": "WhatsApp"}.get(channels, channels)
    header = ai_prompt_blocks.fill(_blocks(blocks)["ctx_history"], limit=limit, scope=scope)
    # Only qualify a heading that still exists - an operator who cleared it does not want a
    # stray ", limited to the past N day(s)" fragment left behind on its own line.
    if lookback_days and header:
        header += f", limited to the past {lookback_days} day(s)"
    if not entries:
        return ai_prompt_blocks.join(header, "No prior messages on file.")
    return ai_prompt_blocks.join(header, "\n".join(entry.text for entry in entries))


def assemble_prompt(
    db: Session,
    *,
    tenant: Tenant,
    template: AiReplyTemplate,
    channel: str,
    rough_draft: str | None,
    inbound_text: str | None = None,
    extra_brain_section_paths: list[str] | None = None,
    knowledge_content: str | None = None,
    previous_draft: str | None = None,
    reviewer_feedback: str | None = None,
    blocks: dict[str, str] | None = None,
    agent_instructions: str | None = None,
    attachment_count: int = 0,
    attachment_names: str = "",
) -> str:
    """Build the exact, single flat prompt string sent to Gemini.

    Fixed order: the drafter profile's preamble and instructions, then 0. guidelines, 1. template
    text/subprompts, 1b. knowledge base (brain sections), 2. message history (all channels),
    3. Beds24 info (booking + payments + notes), the guest message being answered, 4. the user's
    typed text, 5. the previous draft on a redraft round, 6. reviewer feedback on that round. Each present group is prefixed
    with its label so the numbering is visible directly in the payload, not just in the template
    editor UI. Those labels are not hardcoded: they come from `blocks`, so an operator can reword
    or delete any of them (a label resolving to an empty string emits the content on its own).
    Groups 4, 5 and 6 are included only if there is something to put in them - there is no default
    filler instruction. This is the single source of truth reused by the "Draft with AI" endpoint,
    the payload preview endpoint and the planner loop, so what the user previews is guaranteed to
    be what is sent.
    """
    text = _blocks(blocks)
    parts: list[str] = []

    preamble = (text["preamble"] or "").strip()
    if preamble:
        parts.append(preamble)

    instructions = (agent_instructions or "").strip()
    if instructions:
        parts.append(ai_prompt_blocks.join(text["instructions_header"], instructions))

    guidelines_content = _build_guidelines_content(db, template, tenant)
    if guidelines_content:
        parts.append(ai_prompt_blocks.join(text["guidelines"], guidelines_content))

    sections_content = _build_sections_prompt(db, template, tenant)
    if sections_content:
        parts.append(ai_prompt_blocks.join(text["sections"], sections_content))

    knowledge_content = (
        knowledge_content
        if knowledge_content is not None
        else _build_knowledge_base(db, template, tenant, extra_brain_section_paths)
    )
    if knowledge_content:
        parts.append(ai_prompt_blocks.join(text["knowledge"], knowledge_content))

    if template.include_history:
        limit = template.history_message_limit or _DEFAULT_HISTORY_LIMIT
        history_content = _build_history_context(db, tenant, limit, blocks=text)
        parts.append(ai_prompt_blocks.join(text["history"], history_content))

    beds24_group: list[str] = []
    if template.include_beds24:
        beds24_group.append(_build_beds24_context(tenant, text))
    if template.include_payments:
        beds24_group.append(_build_payments_context(db, tenant, text))
    if template.include_notes:
        beds24_group.append(_build_notes_context(tenant, text))
    if template.include_availability:
        beds24_group.append(_build_availability_context(db, text))
    if beds24_group:
        parts.append(ai_prompt_blocks.join(text["beds24"], "\n\n".join(beds24_group)))

    # The guest's actual message, emitted regardless of `template.include_history`. The
    # drafter used to receive this only as a side effect of history being switched on, so a
    # history-less template had it writing a reply it had never read the question for.
    inbound_message = (inbound_text or "").strip()
    if inbound_message:
        parts.append(ai_prompt_blocks.join(text["ctx_inbound"], inbound_message))

    user_message = (rough_draft or "").strip()
    if user_message:
        parts.append(ai_prompt_blocks.join(text["user_instruction"], user_message))

    prior_draft = (previous_draft or "").strip()
    if prior_draft:
        parts.append(ai_prompt_blocks.join(text["previous_draft"], prior_draft))

    feedback = (reviewer_feedback or "").strip()
    if feedback:
        parts.append(ai_prompt_blocks.join(text["reviewer_feedback"], feedback))

    if attachment_count:
        attachment_block = (text["attachment_instruction"] or "").strip()
        if attachment_block:
            parts.append(ai_prompt_blocks.fill(attachment_block, count=attachment_count, names=attachment_names))

    return "\n\n".join(part for part in parts if part.strip())


def build_prompt_and_generate(
    db: Session,
    *,
    tenant: Tenant,
    template: AiReplyTemplate,
    channel: str,
    rough_draft: str | None,
    inbound_text: str | None = None,
    extra_brain_section_paths: list[str] | None = None,
    reviewer_feedback: str | None = None,
    blocks: dict[str, str] | None = None,
    agent_instructions: str | None = None,
) -> str:
    prompt = assemble_prompt(
        db,
        tenant=tenant,
        template=template,
        channel=channel,
        rough_draft=rough_draft,
        inbound_text=inbound_text,
        extra_brain_section_paths=extra_brain_section_paths,
        reviewer_feedback=reviewer_feedback,
        blocks=blocks,
        agent_instructions=agent_instructions,
    )
    return gemini_client.generate_text_flat(prompt)
