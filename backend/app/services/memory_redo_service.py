"""Reads redo feedback and proposes working-memory or rule changes for a human to review.

The legacy `propose_updates_from_redo` path still exists for callers that only have the redone
text plus a "what/why" summary. The new `process_redo_request_log` path is the real redo-log
consumer: it reads the persisted redo log row, builds the prompt from that durable record, and
creates rule-change suggestions plus a full `AiAgentRun` audit trail.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ai_agent_profile import MEMORY_REDO_ROLE, AiAgentProfile
from app.models.ai_agent_run import STATUS_COMPLETED, STATUS_FAILED, STATUS_SKIPPED, AiAgentRun, AiAgentRunStep
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_reply_template import AiReplyTemplate
from app.models.memory_suggestion import (
    KIND_BRAIN_ENTRY,
    KIND_FIELD_VALUE,
    KIND_PROFILE_CHANGE,
    KIND_RULE_ADD,
    KIND_RULE_DELETE,
    KIND_RULE_MODIFY,
    KIND_TEMPLATE_CHANGE,
    STATUS_PENDING,
    MemorySuggestion,
)
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.services import ai_agent_orchestrator, ai_prompt_blocks, beds24_availability_service, brain_field_service, gemini_client, tenant_brain_service, working_memory_rule_service

logger = logging.getLogger(__name__)

# Truncate each step's prompt/response before putting it in the redo prompt, so a long run log
# can't blow up the memory_redo call's own token budget.
_RUN_LOG_STEP_CHAR_LIMIT = 4000

_LEGACY_VALID_KINDS = {
    KIND_FIELD_VALUE,
    KIND_BRAIN_ENTRY,
    KIND_RULE_ADD,
    KIND_RULE_MODIFY,
    KIND_RULE_DELETE,
    KIND_PROFILE_CHANGE,
    KIND_TEMPLATE_CHANGE,
}
# Historically "rule diffs only" - now also covers profile/template suggestions surfaced by
# comparing the redo feedback against the full run log, so the name no longer describes its
# whole scope; kept as-is since nothing outside this module references it by name.
_RULE_VALID_KINDS = {KIND_RULE_ADD, KIND_RULE_MODIFY, KIND_RULE_DELETE, KIND_PROFILE_CHANGE, KIND_TEMPLATE_CHANGE}

_SUGGESTION_ITEM_PROPERTIES = {
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
    # profile_change only - profile_id must be one of the ids named in the run log
    "profile_id": {"type": "integer"},
    # template_change only - template_id must be the final_template_id named in the run log
    "template_id": {"type": "integer"},
    # profile_change / template_change: which field to change (e.g. "instructions", "guidelines")
    # and the suggested replacement text for it
    "field": {"type": "string"},
    "suggested_text": {"type": "string"},
    # template_change only, when field="sections" - must be one of the section_id values listed
    # under the run log's template sections, never invented
    "section_id": {"type": "string"},
    "reasoning": {"type": "string"},
}

MEMORY_REDO_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    # An unconstrained string here lets the model invent plausible-but-wrong
                    # values (e.g. "add_global_rule" instead of "rule_add") that _create_suggestions
                    # then silently drops - the enum is what actually pins the model to the
                    # literals the code checks for; the comment alone is invisible to it.
                    "kind": {"type": "string", "enum": sorted(_LEGACY_VALID_KINDS)},
                    **_SUGGESTION_ITEM_PROPERTIES,
                },
                "required": ["kind", "reasoning"],
            },
        },
    },
    "required": ["suggestions"],
}

RULE_REDO_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": sorted(_RULE_VALID_KINDS)},
                    **_SUGGESTION_ITEM_PROPERTIES,
                },
                "required": ["kind", "reasoning"],
            },
        },
    },
    "required": ["suggestions"],
}

def _recent_decisions_lines(db: Session, tenant_id: int) -> list[str]:
    recent_drafts = (
        db.query(AiAutoDraft)
        .filter(AiAutoDraft.tenant_id == tenant_id, AiAutoDraft.resolution_reason.isnot(None))
        .order_by(AiAutoDraft.updated_at.desc())
        .limit(10)
        .all()
    )
    return [f"- {draft.status} ({draft.resolution_source}): {draft.resolution_reason}" for draft in recent_drafts]


def _fields_and_rules_block(db: Session, tenant_id: int, blocks: dict[str, str]) -> str:
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
        ai_prompt_blocks.join(blocks["ctx_fields"], "\n".join(field_lines) or "None defined."),
        ai_prompt_blocks.join(blocks["ctx_entries"], "\n".join(entry_lines) or "None yet."),
        ai_prompt_blocks.join(blocks["ctx_rules"], "\n".join(rule_lines) or "None yet."),
        ai_prompt_blocks.join(blocks["ctx_availability"], beds24_availability_service.get_cached_summary(db)),
        ai_prompt_blocks.join(blocks["ctx_recent_decisions"], "\n".join(_recent_decisions_lines(db, tenant_id)) or "None yet."),
    ]
    return "\n\n".join(parts)


def _truncate(text: str | None) -> str:
    text = text or ""
    if len(text) <= _RUN_LOG_STEP_CHAR_LIMIT:
        return text
    return text[:_RUN_LOG_STEP_CHAR_LIMIT] + "\n[...truncated]"


def _run_log_block(db: Session, blocks: dict[str, str], agent_run_id: int | None) -> str:
    """Render the full planner/drafter/checker log of the run being redone, so the model can
    tell whether the mistake came from that run's agent instructions or reply template, rather
    than only ever seeing the redone text in isolation.
    """
    if agent_run_id is None:
        return ""
    run = db.query(AiAgentRun).filter(AiAgentRun.id == agent_run_id).first()
    if run is None:
        return ""
    steps = (
        db.query(AiAgentRunStep)
        .filter(AiAgentRunStep.run_id == run.id)
        .order_by(AiAgentRunStep.step_index, AiAgentRunStep.id)
        .all()
    )
    lines = [
        f"run_id={run.id} status={run.status} planner_profile_id={run.planner_profile_id} "
        f"checker_profile_id={run.checker_profile_id} final_template_id={run.final_template_id} "
        f"attempts={run.attempts}"
    ]
    if run.final_template_id is not None:
        template = db.query(AiReplyTemplate).filter(AiReplyTemplate.id == run.final_template_id).first()
        if template is not None:
            for section in template.sections or []:
                section_id = section.get("id") if isinstance(section, dict) else None
                label = section.get("label") if isinstance(section, dict) else None
                if section_id:
                    lines.append(f"- section_id={section_id} | {label or '(untitled section)'}")
    for step in steps:
        lines.append(f"--- step {step.step_index} ({step.stage}, model={step.model}) ---")
        lines.append(f"Prompt:\n{_truncate(step.prompt)}")
        if step.response:
            lines.append(f"Response:\n{_truncate(step.response)}")
        if step.error:
            lines.append(f"Error: {step.error}")
    return ai_prompt_blocks.join(blocks["ctx_run_log"], "\n".join(lines))


def _build_legacy_prompt(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    generated_text: str,
    what: str,
    why: str | None,
    agent_run_id: int | None = None,
) -> str:
    blocks = ai_prompt_blocks.resolve_blocks(profile, MEMORY_REDO_ROLE)
    parts: list[str] = []

    preamble = (blocks["preamble"] or "").strip()
    if preamble:
        parts.append(preamble)

    instructions = (profile.instructions or "").strip()
    if instructions:
        parts.append(ai_prompt_blocks.join(blocks["instructions_header"], instructions))

    parts.append(_fields_and_rules_block(db, tenant.id, blocks))
    parts.append(ai_prompt_blocks.join(blocks["draft"], generated_text or ""))

    redo_lines = [f"What to change: {what}"]
    if why:
        redo_lines.append(f"Why: {why}")
    parts.append(ai_prompt_blocks.join(blocks["ctx_redo"], "\n".join(redo_lines)))

    run_log = _run_log_block(db, blocks, agent_run_id)
    if run_log:
        parts.append(run_log)

    output = (blocks["output"] or "").strip()
    if output:
        parts.append(output)
    return "\n\n".join(part for part in parts if part.strip())


def _build_rule_redo_prompt(db: Session, log: RedoRequestLog, profile: AiAgentProfile, draft_text: str, agent_run_id: int | None) -> str:
    tenant = db.query(Tenant).filter(Tenant.id == log.tenant_id).first()
    if tenant is None:
        return ""

    blocks = ai_prompt_blocks.resolve_blocks(profile, MEMORY_REDO_ROLE)
    parts: list[str] = []

    preamble = (blocks["preamble"] or "").strip()
    if preamble:
        parts.append(preamble)

    instructions = (profile.instructions or "").strip()
    if instructions:
        parts.append(ai_prompt_blocks.join(blocks["instructions_header"], instructions))

    parts.append(_fields_and_rules_block(db, tenant.id, blocks))

    redo_lines = [
        f"Redo log id: {log.id}",
        f"Channel: {log.channel}",
        f"What: {log.what}",
    ]
    if log.why:
        redo_lines.append(f"Why: {log.why}")
    redo_lines.append("## Original Draft")
    redo_lines.append(draft_text or "")
    parts.append(ai_prompt_blocks.join(blocks["ctx_redo"], "\n".join(redo_lines)))

    run_log = _run_log_block(db, blocks, agent_run_id)
    if run_log:
        parts.append(run_log)

    output = (blocks["output"] or "").strip()
    if output:
        parts.append(output)
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
    if kind == KIND_PROFILE_CHANGE:
        profile_id = item.get("profile_id")
        field = str(item.get("field") or "").strip()
        suggested_text = str(item.get("suggested_text") or "").strip()
        if not isinstance(profile_id, int) or not field or not suggested_text:
            return None
        return {"profile_id": profile_id, "field": field, "suggested_text": suggested_text}
    if kind == KIND_TEMPLATE_CHANGE:
        template_id = item.get("template_id")
        field = str(item.get("field") or "").strip()
        suggested_text = str(item.get("suggested_text") or "").strip()
        section_id = str(item.get("section_id") or "").strip() or None
        if not isinstance(template_id, int) or not field or not suggested_text:
            return None
        return {"template_id": template_id, "field": field, "section_id": section_id, "suggested_text": suggested_text}
    return None


def _suggestion_exists(db: Session, *, redo_log_id: int | None, kind: str, target_id: int | None, proposed_value: dict) -> bool:
    if redo_log_id is None:
        return False
    existing = db.query(MemorySuggestion).filter(MemorySuggestion.source_redo_log_id == redo_log_id).all()
    return any(
        suggestion.kind == kind
        and suggestion.target_id == target_id
        and suggestion.proposed_value == proposed_value
        for suggestion in existing
    )


def _create_suggestions(
    db: Session,
    *,
    tenant: Tenant,
    raw_suggestions: list[dict],
    valid_kinds: set[str],
    redo_log_id: int | None = None,
) -> list[MemorySuggestion]:
    definitions_by_key = {d.key: d for d in brain_field_service.list_definitions(db, active_only=True)}

    created: list[MemorySuggestion] = []
    for item in raw_suggestions:
        kind = str((item or {}).get("kind") or "").strip()
        if kind not in valid_kinds:
            # The schema's enum should prevent this, but log rather than silently drop it in
            # case the model ever violates it (or a future kind is added to the schema without
            # updating valid_kinds here) - a run that logs "completed" with zero suggestions
            # actually created is otherwise indistinguishable from one that genuinely found
            # nothing worth proposing.
            logger.warning("Memory redo suggestion dropped: unrecognized kind=%r tenant_id=%s item=%r", kind, tenant.id, item)
            continue
        proposed_value = _build_proposed_value(item or {})
        if proposed_value is None:
            logger.warning("Memory redo suggestion dropped: incomplete fields for kind=%s tenant_id=%s item=%r", kind, tenant.id, item)
            continue

        target_id = proposed_value.get("rule_id")
        if kind == KIND_FIELD_VALUE:
            definition = definitions_by_key.get(proposed_value["field_key"])
            if definition is None:
                logger.warning(
                    "Memory redo suggestion dropped: unknown field_key=%r tenant_id=%s", proposed_value["field_key"], tenant.id
                )
                continue
            target_id = definition.id
        elif kind == KIND_PROFILE_CHANGE:
            target_id = proposed_value["profile_id"]
        elif kind == KIND_TEMPLATE_CHANGE:
            target_id = proposed_value["template_id"]
            section_id = proposed_value.get("section_id")
            if section_id is not None:
                template = db.query(AiReplyTemplate).filter(AiReplyTemplate.id == target_id).first()
                known_section_ids = {
                    section.get("id") for section in (template.sections or []) if isinstance(section, dict)
                } if template is not None else set()
                if section_id not in known_section_ids:
                    logger.warning(
                        "Memory redo suggestion dropped: unknown section_id=%r template_id=%s tenant_id=%s",
                        section_id, target_id, tenant.id,
                    )
                    continue

        if _suggestion_exists(db, redo_log_id=redo_log_id, kind=kind, target_id=target_id, proposed_value=proposed_value):
            continue

        suggestion = MemorySuggestion(
            kind=kind,
            tenant_id=None if kind in (KIND_RULE_ADD, KIND_RULE_MODIFY, KIND_RULE_DELETE, KIND_PROFILE_CHANGE, KIND_TEMPLATE_CHANGE) else tenant.id,
            target_id=target_id,
            proposed_value=proposed_value,
            reasoning=str((item or {}).get("reasoning") or "").strip() or None,
            source_redo_log_id=redo_log_id,
            status=STATUS_PENDING,
        )
        db.add(suggestion)
        created.append(suggestion)
    return created


def _run_model_call(
    db: Session,
    *,
    tenant: Tenant,
    profile: AiAgentProfile,
    prompt: str,
    schema: dict,
    mode: str,
) -> tuple[AiAgentRun, gemini_client.GenerationResult | None]:
    run = AiAgentRun(tenant_id=tenant.id, channel="crm", mode=mode, status=STATUS_FAILED, planner_profile_id=profile.id)
    db.add(run)
    db.flush()
    started = time.monotonic()
    try:
        result = gemini_client.generate(
            prompt,
            model=profile.model,
            temperature=profile.temperature,
            max_output_tokens=profile.max_output_tokens,
            response_schema=schema,
        )
    except gemini_client.GeminiClientError as exc:
        db.add(AiAgentRunStep(run_id=run.id, step_index=0, stage=mode, prompt=prompt, error=str(exc), model=profile.model))
        run.status = STATUS_FAILED
        run.duration_ms = int((time.monotonic() - started) * 1000)
        logger.warning("Memory redo call failed tenant_id=%s error=%s", tenant.id, exc)
        return run, None

    db.add(
        AiAgentRunStep(
            run_id=run.id,
            step_index=0,
            stage=mode,
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
    return run, result


def propose_updates(
    db: Session,
    *,
    tenant: Tenant,
    generated_text: str,
    channel: str,
    what: str,
    why: str | None,
    redo_log_id: int | None = None,
    agent_run_id: int | None = None,
) -> list[MemorySuggestion]:
    """The channel-agnostic core: works from a tenant and whatever text was redone, regardless
    of whether that text lives in a persisted AiAutoDraft or was only ever in the reply box.
    """
    profile = ai_agent_orchestrator.resolve_profile(db, MEMORY_REDO_ROLE, None)
    if profile is None:
        return []

    prompt = _build_legacy_prompt(db, tenant, profile, generated_text, what, why, agent_run_id)
    run, result = _run_model_call(db, tenant=tenant, profile=profile, prompt=prompt, schema=MEMORY_REDO_SCHEMA, mode="memory_redo")
    if result is None:
        return []

    plan = result.parsed or {}
    raw_suggestions = plan.get("suggestions") or []
    if not raw_suggestions:
        run.status = STATUS_SKIPPED
        return []

    created = _create_suggestions(db, tenant=tenant, raw_suggestions=raw_suggestions, valid_kinds=_LEGACY_VALID_KINDS, redo_log_id=redo_log_id)
    run.status = STATUS_COMPLETED
    return created


def process_redo_request_log(db: Session, redo_log_id: int) -> list[MemorySuggestion]:
    log = db.query(RedoRequestLog).filter(RedoRequestLog.id == redo_log_id).first()
    if log is None:
        return []
    existing = db.query(MemorySuggestion).filter(MemorySuggestion.source_redo_log_id == log.id).all()
    if log.processed_at is not None:
        return existing

    tenant = db.query(Tenant).filter(Tenant.id == log.tenant_id).first()
    if tenant is None:
        return existing

    profile = ai_agent_orchestrator.resolve_profile(db, MEMORY_REDO_ROLE, None)
    if profile is None:
        return existing

    draft_text = ""
    agent_run_id = log.ai_agent_run_id
    if log.ai_auto_draft_id is not None:
        draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == log.ai_auto_draft_id).first()
        draft_text = draft.generated_text or "" if draft is not None else ""
        agent_run_id = agent_run_id or (draft.agent_run_id if draft is not None else None)
    elif log.ai_agent_run_id is not None:
        run = db.query(AiAgentRun).filter(AiAgentRun.id == log.ai_agent_run_id).first()
        draft_text = run.final_text or "" if run is not None else ""

    prompt = _build_rule_redo_prompt(db, log, profile, draft_text, agent_run_id)
    if not prompt:
        return existing

    run, result = _run_model_call(db, tenant=tenant, profile=profile, prompt=prompt, schema=RULE_REDO_SCHEMA, mode="memory_redo")
    if result is None:
        return existing

    plan = result.parsed or {}
    raw_suggestions = plan.get("suggestions") or []
    created = _create_suggestions(db, tenant=tenant, raw_suggestions=raw_suggestions, valid_kinds=_RULE_VALID_KINDS, redo_log_id=log.id)
    run.status = STATUS_COMPLETED if raw_suggestions else STATUS_SKIPPED
    log.memory_redo_run_id = run.id
    log.processed_at = datetime.now(timezone.utc)
    return created or existing


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
        agent_run_id=draft.agent_run_id,
        redo_log_id=redo_log_id,
    )
