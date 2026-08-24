"""Answers a staff member's ad-hoc question about one tenant's working memory - grounded in
that tenant's structured fields, free-text brain entries, action items, prior QA turns, and
whatever tenant context the configured profile allows. Read-only: this never writes to the
brain, fields, or action list.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.action_item import ActionItem
from app.models.ai_agent_profile import MEMORY_QA_ROLE, AiAgentProfile
from app.models.memory_qa_message import ROLE_ASSISTANT, ROLE_USER, MemoryQaMessage
from app.models.tenant import Tenant
from app.services import ai_agent_orchestrator, ai_prompt_blocks, ai_reply_service, brain_field_service, brain_service, gemini_client, tenant_brain_service

_PREAMBLE = (
    "You answer a staff member's question about one tenant in a short-stay rental CRM, using "
    "only the working-memory context provided below. If the context doesn't contain the "
    "answer, say so plainly rather than guessing."
)

_QA_HISTORY_LIMIT = 10


def _flag(profile: AiAgentProfile | None, name: str, default: bool) -> bool:
    return bool(getattr(profile, name, default)) if profile is not None else default


def _fields_block(db: Session, tenant_id: int, blocks: dict[str, str]) -> str:
    definitions = brain_field_service.list_definitions(db, active_only=True)
    values = brain_field_service.get_values_for_tenant(db, tenant_id)
    lines = [
        f"- {d.label}: {values[d.id].value if d.id in values and values[d.id].value else '(not set)'}"
        for d in definitions
    ]
    return ai_prompt_blocks.join(blocks["ctx_fields"], "\n".join(lines) or "None defined.")


def _entries_block(db: Session, tenant_id: int, blocks: dict[str, str]) -> str:
    entries = tenant_brain_service.list_entries(db, tenant_id)
    lines = [f"- {entry.content}" for entry in entries]
    return ai_prompt_blocks.join(blocks["ctx_entries"], "\n".join(lines) or "None yet.")


def _action_items_block(db: Session, tenant_id: int, blocks: dict[str, str]) -> str:
    items = (
        db.query(ActionItem)
        .filter(ActionItem.tenant_id == tenant_id)
        .order_by(ActionItem.created_at.desc())
        .all()
    )
    lines = [f"- [{item.status}] {item.title}" for item in items]
    return ai_prompt_blocks.join(blocks["ctx_actions"], "\n".join(lines) or "None yet.")


def _tenant_history_block(db: Session, tenant: Tenant, profile: AiAgentProfile | None, blocks: dict[str, str]) -> str:
    limit = max(0, int(getattr(profile, "history_limit", 0) or 0))
    if limit <= 0:
        return ""
    context_blocks = dict(blocks)
    context_blocks["ctx_history"] = blocks["ctx_tenant_history"]
    channels = ai_agent_orchestrator._resolve_history_channels(profile, "both") if profile is not None else "both"
    return ai_reply_service._build_history_context(
        db,
        tenant,
        limit,
        channels=channels,
        lookback_days=getattr(profile, "history_lookback_days", None) if profile is not None else None,
        blocks=context_blocks,
    )


def _qa_history_block(history: list[MemoryQaMessage], blocks: dict[str, str]) -> str:
    if not history:
        return ""
    lines = [f"{'Staff' if m.role == ROLE_USER else 'Assistant'}: {m.content}" for m in history[-_QA_HISTORY_LIMIT:]]
    return ai_prompt_blocks.join(blocks["ctx_history"], "\n".join(lines))


def _build_prompt(db: Session, tenant: Tenant, profile: AiAgentProfile | None, history: list[MemoryQaMessage], question: str) -> str:
    blocks = ai_prompt_blocks.resolve_blocks(profile, MEMORY_QA_ROLE)
    parts: list[str] = [_PREAMBLE]

    instructions = (profile.instructions or "").strip() if profile is not None else ""
    if instructions:
        parts.append(ai_prompt_blocks.join(blocks["instructions_header"], instructions))

    tenant_history = _tenant_history_block(db, tenant, profile, blocks)
    if tenant_history:
        parts.append(tenant_history)

    parts.append(_fields_block(db, tenant.id, blocks))
    parts.append(_entries_block(db, tenant.id, blocks))
    parts.append(_action_items_block(db, tenant.id, blocks))

    if _flag(profile, "include_brain_index", True):
        parts.append(ai_prompt_blocks.join(blocks["ctx_brain_index"], brain_service.build_brain_index(db)))
    if _flag(profile, "include_beds24", True):
        parts.append(ai_reply_service._build_beds24_context(tenant, blocks))
    if _flag(profile, "include_payments", False):
        parts.append(ai_reply_service._build_payments_context(db, tenant, blocks))
    if _flag(profile, "include_notes", True):
        parts.append(ai_reply_service._build_notes_context(tenant, blocks))
    if _flag(profile, "include_availability", False):
        parts.append(ai_reply_service._build_availability_context(db, blocks))

    qa_history = _qa_history_block(history, blocks)
    if qa_history:
        parts.append(qa_history)
    parts.append(ai_prompt_blocks.join(blocks["ctx_question"], question))
    return "\n\n".join(part for part in parts if part.strip())


def list_history(db: Session, tenant_id: int, limit: int = 50) -> list[MemoryQaMessage]:
    return (
        db.query(MemoryQaMessage)
        .filter(MemoryQaMessage.tenant_id == tenant_id)
        .order_by(MemoryQaMessage.created_at.asc(), MemoryQaMessage.id.asc())
        .limit(limit)
        .all()
    )


def answer_question(db: Session, tenant: Tenant, question: str, asked_by_user_id: int | None = None) -> MemoryQaMessage:
    question = (question or "").strip()
    profile = ai_agent_orchestrator.resolve_profile(db, MEMORY_QA_ROLE, None)
    history = list_history(db, tenant.id)

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
