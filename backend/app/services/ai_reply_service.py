from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.ai_reply_template import AiReplyTemplate
from app.models.finance import Finance as FinanceRecord
from app.models.gmail_integration import ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.services import gemini_client
from app.services.email_template_service import resolve_template_text
from app.services.thread_timeline_service import ensure_utc as _ensure_utc, load_tenant_whatsapp_messages

_DEFAULT_HISTORY_LIMIT = 20


@dataclass(frozen=True)
class _HistoryEntry:
    timestamp: datetime
    sort_id: int
    text: str


def _build_guidelines_content(template: AiReplyTemplate, tenant: Tenant) -> str:
    return resolve_template_text((template.guidelines or "").strip(), tenant)


def _build_sections_prompt(template: AiReplyTemplate, tenant: Tenant) -> str:
    sections = template.sections or []
    blocks: list[str] = []
    for section in sections:
        label = str(section.get("label") or "").strip()
        content = resolve_template_text(str(section.get("content") or "").strip(), tenant)
        if not content:
            continue
        blocks.append(f"## {label}\n{content}" if label else content)
    return "\n\n".join(blocks)


def _build_beds24_context(tenant: Tenant) -> str:
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
    return "## Booking Information (Beds24)\n" + "\n".join(lines)


def _build_payments_context(db: Session, tenant: Tenant) -> str:
    records = (
        db.query(FinanceRecord)
        .filter(FinanceRecord.tenant_id == tenant.id)
        .order_by(FinanceRecord.created_at.asc(), FinanceRecord.id.asc())
        .all()
    )
    if not records:
        return "## Payments & Charges\nNo payment or charge records on file."

    lines = [
        f"- {record.type}: {record.amount} {record.currency} — {record.description or 'no description'}"
        for record in records
    ]
    return "## Payments & Charges\n" + "\n".join(lines)


def _load_email_history(db: Session, tenant_id: int, limit: int) -> list[_HistoryEntry]:
    """Most recent `limit` email messages across every linked thread of this tenant."""
    messages = (
        db.query(ConversationMessage)
        .join(TenantConversationLink, TenantConversationLink.conversation_id == ConversationMessage.conversation_id)
        .filter(TenantConversationLink.tenant_id == tenant_id, TenantConversationLink.unlinked_at.is_(None))
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


def _build_notes_context(tenant: Tenant) -> str:
    notes = (tenant.notes or "").strip()
    if not notes:
        return "## Internal Notes\nNo internal notes on file."
    return "## Internal Notes\n" + notes


def _build_history_context(db: Session, tenant: Tenant, limit: int) -> str:
    """Last `limit` messages for this tenant across *all* channels, oldest first.

    The history is deliberately channel-agnostic: a reply on one channel routinely depends on what
    was said on the other, so both email (every linked thread, not just the one being replied to)
    and WhatsApp are merged into a single chronological stream and only then truncated to `limit`.
    Each line carries its channel so the model can tell the two mediums apart.
    """
    entries = _load_email_history(db, tenant.id, limit) + _load_whatsapp_history(db, tenant.id, limit)
    entries.sort(key=lambda entry: (entry.timestamp, entry.sort_id))
    entries = entries[-limit:] if limit > 0 else []

    header = f"## Conversation History (last {limit} messages across email and WhatsApp)"
    if not entries:
        return f"{header}\nNo prior messages on file."
    return header + "\n" + "\n".join(entry.text for entry in entries)


def assemble_prompt(
    db: Session,
    *,
    tenant: Tenant,
    template: AiReplyTemplate,
    channel: str,
    rough_draft: str | None,
) -> str:
    """Build the exact, single flat prompt string sent to Gemini.

    Fixed order: 0. guidelines, 1. template text/subprompts, 2. message history (all channels),
    3. Beds24 info (booking + payments + notes), 4. the user's typed text. Each present
    group is prefixed with its position number so the numbering is visible directly in
    the payload, not just in the template editor UI. Group 4 is included only if the
    user actually typed something - there is no default filler instruction. This is the
    single source of truth reused by both the "Draft with AI" generation endpoint and the
    payload preview endpoint, so what the user previews is guaranteed to be what is sent.
    """
    blocks: list[str] = []

    guidelines_content = _build_guidelines_content(template, tenant)
    if guidelines_content:
        blocks.append(f"0. Goal & Guidelines\n{guidelines_content}")

    sections_content = _build_sections_prompt(template, tenant)
    if sections_content:
        blocks.append(f"1. Template Text\n{sections_content}")

    if template.include_history:
        limit = template.history_message_limit or _DEFAULT_HISTORY_LIMIT
        history_content = _build_history_context(db, tenant, limit)
        blocks.append(f"2. Message History\n{history_content}")

    beds24_group: list[str] = []
    if template.include_beds24:
        beds24_group.append(_build_beds24_context(tenant))
    if template.include_payments:
        beds24_group.append(_build_payments_context(db, tenant))
    if template.include_notes:
        beds24_group.append(_build_notes_context(tenant))
    if beds24_group:
        blocks.append("3. Beds24 Info\n" + "\n\n".join(beds24_group))

    user_message = (rough_draft or "").strip()
    if user_message:
        blocks.append(f"4. Your Instruction\n{user_message}")

    return "\n\n".join(block for block in blocks if block.strip())


def build_prompt_and_generate(
    db: Session,
    *,
    tenant: Tenant,
    template: AiReplyTemplate,
    channel: str,
    rough_draft: str | None,
) -> str:
    prompt = assemble_prompt(db, tenant=tenant, template=template, channel=channel, rough_draft=rough_draft)
    return gemini_client.generate_text_flat(prompt)
