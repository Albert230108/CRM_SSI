"""Reads a redo's "what"/"why" feedback and proposes working-memory/rule changes for a human
to review - see memory_suggestion_service for what applying an approved suggestion actually
does. Never applies anything itself; every suggestion is created with status="pending".

Deliberately does not read working_memory_rule_service.list_active() into the prompt as
consumable instructions (rules are not wired into any drafting prompt yet - see
working_memory_rule.py) but it does read the existing rule list so it can propose sensible
rule_modify/rule_delete targets and avoid suggesting near-duplicate rule_add entries.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.models.ai_agent_profile import MEMORY_REDO_ROLE, AiAgentProfile
from app.models.ai_agent_run import STATUS_COMPLETED, STATUS_FAILED, STATUS_SKIPPED, AiAgentRun, AiAgentRunStep
from app.models.ai_auto_draft import AiAutoDraft
from app.models.memory_suggestion import (
    KIND_BRAIN_ENTRY,
    KIND_FIELD_VALUE,
    KIND_RULE_ADD,
    KIND_RULE_DELETE,
    KIND_RULE_MODIFY,
    STATUS_PENDING,
    MemorySuggestion,
)
from app.models.tenant import Tenant
from app.services import ai_agent_orchestrator, ai_prompt_blocks, brain_field_service, gemini_client, tenant_brain_service, working_memory_rule_service

logger = logging.getLogger(__name__)

_VALID_KINDS = {KIND_FIELD_VALUE, KIND_BRAIN_ENTRY, KIND_RULE_ADD, KIND_RULE_MODIFY, KIND_RULE_DELETE}

MEMORY_REDO_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    # One of: field_value | brain_entry | rule_add | rule_modify | rule_delete
                    "kind": {"type": "string"},
                    # field_value only
                    "field_key": {"type": "string"},
                    "value": {"type": "string"},
                    # brain_entry only
                    "content": {"type": "string"},
                    # rule_modify / rule_delete only
                    "rule_id": {"type": "integer"},
                    # rule_add, and rule_modify's replacement text
                    "condition_text": {"type": "string"},
                    "action_text": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["kind", "reasoning"],
            },
        },
    },
    "required": ["suggestions"],
}

_PREAMBLE = (
    "A staff member asked to redo an AI-generated reply in a short-stay rental CRM, explaining "
    "what to change and why. Decide whether that feedback reveals something worth permanently "
    "changing in this tenant's working memory, or in a general rule that would apply across "
    "tenants. Most redos are one-off wording notes and warrant no suggestion at all - only "
    "propose a change when the \"why\" points at a durable, generalizable fact or policy, not a "
    "one-time stylistic tweak."
)

_OUTPUT_INSTRUCTION = (
    "## Output\n"
    "Return JSON only. `suggestions` is a list of 0 or more proposed changes, each with a "
    "`kind`, the fields relevant to that kind, and a `reasoning` explaining why it's durable "
    "and generalizable rather than one-off. Leave `suggestions` empty when in doubt."
)


def _fields_and_rules_block(db: Session, tenant_id: int) -> str:
    definitions = brain_field_service.list_definitions(db, active_only=True)
    values = brain_field_service.get_values_for_tenant(db, tenant_id)
    field_lines = [
        f"- key={d.key} | {d.label} | current: {values[d.id].value if d.id in values and values[d.id].value else '(not set)'}"
        for d in definitions
    ]
    entries = tenant_brain_service.list_entries(db, tenant_id)
    entry_lines = [f"- {entry.content}" for entry in entries]
    rules = working_memory_rule_service.list_active(db)
    rule_lines = [f"- id={rule.id} | if {rule.condition_text} then {rule.action_text}" for rule in rules]

    parts = [
        ai_prompt_blocks.join("## Structured Fields (key | label | current value)", "\n".join(field_lines) or "None defined."),
        ai_prompt_blocks.join("## Free-Text Brain Entries", "\n".join(entry_lines) or "None yet."),
        ai_prompt_blocks.join("## Existing Global Rules (id | condition -> action)", "\n".join(rule_lines) or "None yet."),
    ]
    return "\n\n".join(parts)


def _build_prompt(db: Session, tenant: Tenant, profile: AiAgentProfile, generated_text: str, what: str, why: str | None) -> str:
    parts: list[str] = [_PREAMBLE]

    instructions = (profile.instructions or "").strip()
    if instructions:
        parts.append(ai_prompt_blocks.join("## Your Instructions", instructions))

    parts.append(_fields_and_rules_block(db, tenant.id))
    parts.append(ai_prompt_blocks.join("## Draft Being Redone", generated_text or ""))

    redo_lines = [f"What to change: {what}"]
    if why:
        redo_lines.append(f"Why: {why}")
    parts.append(ai_prompt_blocks.join("## Redo Feedback", "\n".join(redo_lines)))

    parts.append(_OUTPUT_INSTRUCTION)
    return "\n\n".join(part for part in parts if part.strip())


def _build_proposed_value(item: dict) -> dict | None:
    kind = str(item.get("kind") or "").strip()
    if kind == KIND_FIELD_VALUE:
        field_key = str(item.get("field_key") or "").strip()
        value = str(item.get("value") or "").strip()
        if not field_key or not value:
            return None
        return {"field_key": field_key, "value": value}
    if kind == KIND_BRAIN_ENTRY:
        content = str(item.get("content") or "").strip()
        if not content:
            return None
        return {"content": content}
    if kind == KIND_RULE_ADD:
        condition_text = str(item.get("condition_text") or "").strip()
        action_text = str(item.get("action_text") or "").strip()
        if not condition_text or not action_text:
            return None
        return {"condition_text": condition_text, "action_text": action_text}
    if kind == KIND_RULE_MODIFY:
        rule_id = item.get("rule_id")
        condition_text = str(item.get("condition_text") or "").strip()
        action_text = str(item.get("action_text") or "").strip()
        if not isinstance(rule_id, int) or (not condition_text and not action_text):
            return None
        return {"rule_id": rule_id, "condition_text": condition_text or None, "action_text": action_text or None}
    if kind == KIND_RULE_DELETE:
        rule_id = item.get("rule_id")
        if not isinstance(rule_id, int):
            return None
        return {"rule_id": rule_id}
    return None


def propose_updates(
    db: Session,
    *,
    tenant: Tenant,
    generated_text: str,
    channel: str,
    what: str,
    why: str | None,
    redo_log_id: int | None = None,
) -> list[MemorySuggestion]:
    """The channel-agnostic core: works from a tenant and whatever text was redone, regardless
    of whether that text lives in a persisted AiAutoDraft or was only ever in the reply box.
    """
    profile = ai_agent_orchestrator.resolve_profile(db, MEMORY_REDO_ROLE, None)
    if profile is None:
        return []

    prompt = _build_prompt(db, tenant, profile, generated_text, what, why)

    run = AiAgentRun(tenant_id=tenant.id, channel=channel, mode="memory_redo", status=STATUS_FAILED, planner_profile_id=profile.id)
    db.add(run)
    db.flush()
    started = time.monotonic()

    try:
        result = gemini_client.generate(
            prompt, model=profile.model, temperature=profile.temperature, max_output_tokens=profile.max_output_tokens, response_schema=MEMORY_REDO_SCHEMA
        )
    except gemini_client.GeminiClientError as exc:
        db.add(AiAgentRunStep(run_id=run.id, step_index=0, stage="memory_redo", prompt=prompt, error=str(exc), model=profile.model))
        run.status = STATUS_FAILED
        run.duration_ms = int((time.monotonic() - started) * 1000)
        logger.warning("Memory redo call failed tenant_id=%s error=%s", tenant.id, exc)
        return []

    db.add(
        AiAgentRunStep(
            run_id=run.id,
            step_index=0,
            stage="memory_redo",
            model=result.model,
            prompt=prompt,
            response=result.text,
            parsed=result.parsed,
            prompt_tokens=result.prompt_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
        )
    )
    run.total_prompt_tokens = result.prompt_tokens or 0
    run.total_output_tokens = result.output_tokens or 0
    run.duration_ms = int((time.monotonic() - started) * 1000)

    plan = result.parsed or {}
    raw_suggestions = plan.get("suggestions") or []
    if not raw_suggestions:
        run.status = STATUS_SKIPPED
        return []

    definitions_by_key = {d.key: d for d in brain_field_service.list_definitions(db, active_only=True)}

    created: list[MemorySuggestion] = []
    for item in raw_suggestions:
        kind = str((item or {}).get("kind") or "").strip()
        if kind not in _VALID_KINDS:
            continue
        proposed_value = _build_proposed_value(item or {})
        if proposed_value is None:
            continue

        target_id = proposed_value.get("rule_id")
        if kind == KIND_FIELD_VALUE:
            definition = definitions_by_key.get(proposed_value["field_key"])
            if definition is None:
                # Hallucinated field key - never invent a dangling suggestion for a field that
                # doesn't exist in the schema.
                continue
            target_id = definition.id

        suggestion = MemorySuggestion(
            kind=kind,
            tenant_id=None if kind in (KIND_RULE_ADD, KIND_RULE_MODIFY, KIND_RULE_DELETE) else tenant.id,
            target_id=target_id,
            proposed_value=proposed_value,
            reasoning=str((item or {}).get("reasoning") or "").strip() or None,
            source_redo_log_id=redo_log_id,
            status=STATUS_PENDING,
        )
        db.add(suggestion)
        created.append(suggestion)

    run.status = STATUS_COMPLETED
    return created


def propose_updates_from_redo(
    db: Session, draft: AiAutoDraft, what: str, why: str | None, *, redo_log_id: int | None = None
) -> list[MemorySuggestion]:
    """The AiAutoDraft-flavoured entry point used by the WhatsApp/CRM approval-flow redo."""
    tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
    if tenant is None:
        return []
    return propose_updates(
        db,
        tenant=tenant,
        generated_text=draft.generated_text or "",
        channel=draft.channel,
        what=what,
        why=why,
        redo_log_id=redo_log_id,
    )
