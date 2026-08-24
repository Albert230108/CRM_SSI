"""Answers a staff member's ad-hoc question about one tenant's working memory - grounded in
that tenant's structured fields, free-text brain entries, action items, and the parsed Beds24
availability summary. Read-only: this never writes to the brain, fields, or action list.

Rules are deliberately excluded from the context here too, consistent with them not being
wired into any prompt yet (see working_memory_rule.py).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.action_item import ActionItem
from app.models.ai_agent_profile import MEMORY_QA_ROLE, AiAgentProfile
from app.models.memory_qa_message import ROLE_ASSISTANT, ROLE_USER, MemoryQaMessage
from app.models.tenant import Tenant
from app.services import ai_agent_orchestrator, ai_prompt_blocks, beds24_availability_service, brain_field_service, gemini_client, tenant_brain_service

_PREAMBLE = (
    "You answer a staff member's question about one tenant in a short-stay rental CRM, using "
    "only the working-memory context provided below. If the context doesn't contain the "
    "answer, say so plainly rather than guessing."
)

_HISTORY_LIMIT = 10


def _fields_block(db: Session, tenant_id: int) -> str:
    definitions = brain_field_service.list_definitions(db, active_only=True)
    values = brain_field_service.get_values_for_tenant(db, tenant_id)
    lines = [
        f"- {d.label}: {values[d.id].value if d.id in values and values[d.id].value else '(not set)'}"
        for d in definitions
    ]
    return ai_prompt_blocks.join("## Structured Fields", "\n".join(lines) or "None defined.")


def _entries_block(db: Session, tenant_id: int) -> str:
    entries = tenant_brain_service.list_entries(db, tenant_id)
    lines = [f"- {entry.content}" for entry in entries]
    return ai_prompt_blocks.join("## Free-Text Brain Entries", "\n".join(lines) or "None yet.")


def _action_items_block(db: Session, tenant_id: int) -> str:
    items = (
        db.query(ActionItem)
        .filter(ActionItem.tenant_id == tenant_id)
        .order_by(ActionItem.created_at.desc())
        .all()
    )
    lines = [f"- [{item.status}] {item.title}" for item in items]
    return ai_prompt_blocks.join("## Action Items", "\n".join(lines) or "None yet.")


def list_history(db: Session, tenant_id: int, limit: int = 50) -> list[MemoryQaMessage]:
    return (
        db.query(MemoryQaMessage)
        .filter(MemoryQaMessage.tenant_id == tenant_id)
        .order_by(MemoryQaMessage.created_at.asc(), MemoryQaMessage.id.asc())
        .limit(limit)
        .all()
    )


def _history_block(history: list[MemoryQaMessage]) -> str:
    if not history:
        return ""
    lines = [f"{'Staff' if m.role == ROLE_USER else 'Assistant'}: {m.content}" for m in history[-_HISTORY_LIMIT:]]
    return ai_prompt_blocks.join("## Prior Questions In This Session", "\n".join(lines))


def _build_prompt(db: Session, tenant: Tenant, profile: AiAgentProfile | None, history: list[MemoryQaMessage], question: str) -> str:
    parts: list[str] = [_PREAMBLE]
    if profile is not None and (profile.instructions or "").strip():
        parts.append(ai_prompt_blocks.join("## Your Instructions", profile.instructions.strip()))
    parts.append(_fields_block(db, tenant.id))
    parts.append(_entries_block(db, tenant.id))
    parts.append(_action_items_block(db, tenant.id))
    parts.append(ai_prompt_blocks.join("## Availability", beds24_availability_service.get_cached_summary(db)))
    history_block = _history_block(history)
    if history_block:
        parts.append(history_block)
    parts.append(ai_prompt_blocks.join("## Question", question))
    return "\n\n".join(part for part in parts if part.strip())


def answer_question(db: Session, tenant: Tenant, question: str, asked_by_user_id: int | None = None) -> MemoryQaMessage:
    question = (question or "").strip()
    history = list_history(db, tenant.id)
    profile = ai_agent_orchestrator.resolve_profile(db, MEMORY_QA_ROLE, None)

    prompt = _build_prompt(db, tenant, profile, history, question)
    try:
        result = gemini_client.generate(
            prompt,
            model=profile.model if profile is not None else None,
            temperature=profile.temperature if profile is not None else None,
            max_output_tokens=profile.max_output_tokens if profile is not None else None,
        )
        answer_text = result.text
    except gemini_client.GeminiClientError:
        answer_text = "Sorry, I couldn't answer that right now - please try again."

    db.add(MemoryQaMessage(tenant_id=tenant.id, role=ROLE_USER, content=question, asked_by_user_id=asked_by_user_id))
    assistant_message = MemoryQaMessage(tenant_id=tenant.id, role=ROLE_ASSISTANT, content=answer_text)
    db.add(assistant_message)
    db.flush()
    return assistant_message
