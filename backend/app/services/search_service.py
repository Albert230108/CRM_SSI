"""Global cross-entity search.

A single case-insensitive substring (ILIKE) search over the human-readable text of every
searchable domain model, returning a flat, uniform list of hits so the frontend can render
any result type the same way. ILIKE + func.lower are portable across Postgres (prod) and
SQLite (tests), so no full-text index or migration is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.action_item import ActionItem
from app.models.ai_reply_template import AiReplyTemplate
from app.models.brain_field_definition import BrainFieldDefinition
from app.models.brain_section import BrainSection
from app.models.communication import Communication
from app.models.communication_reply_draft import CommunicationReplyDraft
from app.models.finance import Finance
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_brain_entry import TenantBrainEntry
from app.models.tenant_brain_field_value import TenantBrainFieldValue
from app.models.working_memory_rule import WorkingMemoryRule

# Characters of surrounding context to keep on each side of the match in a snippet.
SNIPPET_RADIUS = 70
# Per-type cap so one noisy entity can never crowd out the rest of the results.
DEFAULT_PER_TYPE_LIMIT = 10


@dataclass
class SearchHit:
    type: str
    id: int
    tenant_id: int | None
    title: str
    snippet: str


def _truncate(text: str | None, limit: int = 90) -> str:
    collapsed = " ".join((text or "").split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _snippet(term: str, *fields: str | None) -> str:
    """Excerpt around the first field that contains ``term``.

    Prefers the field the match is actually in; falls back to the first non-empty field so a
    result still shows context even when the match was on a short field (e.g. an email address)
    that is not worth quoting.
    """
    lowered_term = term.lower()
    for field in fields:
        if not field:
            continue
        idx = field.lower().find(lowered_term)
        if idx == -1:
            continue
        start = max(0, idx - SNIPPET_RADIUS)
        end = min(len(field), idx + len(term) + SNIPPET_RADIUS)
        excerpt = " ".join(field[start:end].split())
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(field) else ""
        return f"{prefix}{excerpt}{suffix}"
    for field in fields:
        if field:
            return _truncate(field, SNIPPET_RADIUS * 2)
    return ""


def _search_tenants(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(Tenant)
        .filter(
            or_(
                Tenant.name.ilike(term),
                Tenant.booking_id.ilike(term),
                Tenant.email.ilike(term),
                Tenant.phone.ilike(term),
                Tenant.mobile.ilike(term),
                Tenant.company.ilike(term),
                Tenant.city.ilike(term),
                Tenant.address.ilike(term),
                Tenant.notes.ilike(term),
            )
        )
        .order_by(Tenant.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="tenant",
            id=t.id,
            tenant_id=t.id,
            title=t.name or f"{t.first_name or ''} {t.last_name or ''}".strip() or t.booking_id or f"Tenant {t.id}",
            snippet=_snippet(q, t.booking_id, t.email, t.company, t.city, t.address, t.notes),
        )
        for t in rows
    ]


def _search_communications(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(Communication)
        .filter(or_(Communication.subject.ilike(term), Communication.message.ilike(term)))
        .order_by(Communication.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="communication",
            id=c.id,
            tenant_id=c.tenant_id,
            title=_truncate(c.subject) or f"{c.channel} message",
            snippet=_snippet(q, c.message, c.subject),
        )
        for c in rows
    ]


def _search_email_messages(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(ConversationMessage, Conversation.tenant_id)
        .join(Conversation, ConversationMessage.conversation_id == Conversation.id)
        .filter(
            or_(
                ConversationMessage.subject.ilike(term),
                ConversationMessage.body.ilike(term),
                ConversationMessage.sender_email.ilike(term),
            )
        )
        .order_by(ConversationMessage.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="email_message",
            id=m.id,
            tenant_id=tenant_id,
            title=_truncate(m.subject) or f"Email from {m.sender_email or 'unknown'}",
            snippet=_snippet(q, m.body, m.subject, m.sender_email),
        )
        for m, tenant_id in rows
    ]


def _search_conversations(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(Conversation)
        .filter(or_(Conversation.subject.ilike(term), Conversation.preview_text.ilike(term)))
        .order_by(Conversation.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="conversation",
            id=c.id,
            tenant_id=c.tenant_id,
            title=_truncate(c.subject) or "Email conversation",
            snippet=_snippet(q, c.preview_text, c.subject),
        )
        for c in rows
    ]


def _search_brain_sections(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(BrainSection)
        .filter(
            or_(
                BrainSection.title.ilike(term),
                BrainSection.path.ilike(term),
                BrainSection.content.ilike(term),
            )
        )
        .order_by(BrainSection.path)
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="brain_section",
            id=s.id,
            tenant_id=None,
            title=s.title,
            snippet=_snippet(q, s.content, s.path),
        )
        for s in rows
    ]


def _search_tenant_brain_entries(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(TenantBrainEntry)
        .filter(TenantBrainEntry.content.ilike(term))
        .order_by(TenantBrainEntry.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="tenant_brain_entry",
            id=e.id,
            tenant_id=e.tenant_id,
            title="Brain note",
            snippet=_snippet(q, e.content),
        )
        for e in rows
    ]


def _search_tenant_brain_fields(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(TenantBrainFieldValue, BrainFieldDefinition.label)
        .join(
            BrainFieldDefinition,
            TenantBrainFieldValue.field_definition_id == BrainFieldDefinition.id,
        )
        .filter(TenantBrainFieldValue.value.ilike(term))
        .order_by(TenantBrainFieldValue.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="tenant_brain_field",
            id=v.id,
            tenant_id=v.tenant_id,
            title=label or "Brain field",
            snippet=_snippet(q, v.value),
        )
        for v, label in rows
    ]


def _search_working_memory_rules(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(WorkingMemoryRule)
        .filter(or_(WorkingMemoryRule.condition_text.ilike(term), WorkingMemoryRule.action_text.ilike(term)))
        .order_by(WorkingMemoryRule.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="working_memory_rule",
            id=r.id,
            tenant_id=None,
            title=_truncate(r.condition_text) or f"Rule {r.id}",
            snippet=_snippet(q, r.action_text, r.condition_text),
        )
        for r in rows
    ]


def _search_action_items(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(ActionItem)
        .filter(or_(ActionItem.title.ilike(term), ActionItem.description.ilike(term)))
        .order_by(ActionItem.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="action_item",
            id=a.id,
            tenant_id=a.tenant_id,
            title=_truncate(a.title) or f"Action {a.id}",
            snippet=_snippet(q, a.description, a.title),
        )
        for a in rows
    ]


def _search_finances(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(Finance)
        .filter(Finance.description.ilike(term))
        .order_by(Finance.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="finance",
            id=f.id,
            tenant_id=f.tenant_id,
            title=f"{f.type} {f.amount} {f.currency}".strip(),
            snippet=_snippet(q, f.description),
        )
        for f in rows
    ]


def _search_reply_drafts(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(CommunicationReplyDraft)
        .filter(or_(CommunicationReplyDraft.subject.ilike(term), CommunicationReplyDraft.body.ilike(term)))
        .order_by(CommunicationReplyDraft.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="reply_draft",
            id=d.id,
            tenant_id=d.tenant_id,
            title=_truncate(d.subject) or f"{d.channel} reply draft",
            snippet=_snippet(q, d.body, d.subject),
        )
        for d in rows
    ]


def _search_ai_templates(db: Session, q: str, term: str, limit: int) -> list[SearchHit]:
    rows = (
        db.query(AiReplyTemplate)
        .filter(
            or_(
                AiReplyTemplate.name.ilike(term),
                AiReplyTemplate.description.ilike(term),
                AiReplyTemplate.guidelines.ilike(term),
            )
        )
        .order_by(AiReplyTemplate.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHit(
            type="ai_template",
            id=t.id,
            tenant_id=None,
            title=t.name or f"Template {t.id}",
            snippet=_snippet(q, t.description, t.guidelines),
        )
        for t in rows
    ]


# Ordered so results group predictably (dict preserves insertion order). The keys are the
# public `type` values the frontend filters on.
_SEARCHERS: dict[str, Callable[[Session, str, str, int], list[SearchHit]]] = {
    "tenant": _search_tenants,
    "communication": _search_communications,
    "email_message": _search_email_messages,
    "conversation": _search_conversations,
    "brain_section": _search_brain_sections,
    "tenant_brain_entry": _search_tenant_brain_entries,
    "tenant_brain_field": _search_tenant_brain_fields,
    "working_memory_rule": _search_working_memory_rules,
    "action_item": _search_action_items,
    "finance": _search_finances,
    "reply_draft": _search_reply_drafts,
    "ai_template": _search_ai_templates,
}

SEARCHABLE_TYPES = tuple(_SEARCHERS.keys())


def search(
    db: Session,
    q: str,
    types: list[str] | None = None,
    per_type_limit: int = DEFAULT_PER_TYPE_LIMIT,
) -> list[SearchHit]:
    """Run the substring search across every (or the selected) entity types.

    ``types`` restricts which entities are queried; unknown type names are ignored so a stale
    client filter can never widen the search. An empty query returns nothing.
    """
    query = (q or "").strip()
    if not query:
        return []
    selected = set(types) if types else None
    term = f"%{query}%"
    hits: list[SearchHit] = []
    for type_name, searcher in _SEARCHERS.items():
        if selected is not None and type_name not in selected:
            continue
        hits.extend(searcher(db, query, term, per_type_limit))
    return hits
