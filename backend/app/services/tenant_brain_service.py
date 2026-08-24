"""The per-tenant "brain": a running list of durable facts staff and the AI both maintain.

Two write paths feed the same TenantBrainEntry table:
  - generate_brain_update_for_trigger: the debounced, per-message automatic path (see
    tenant_brain_trigger_service.py and the scheduler sweep in main.py).
  - scan_tenant_history: the manual, on-demand "Generate initial brain" path, run synchronously
    from the API request that triggered it.
Manual add/edit/delete from the UI go through add_entry/update_entry/delete_entry directly.

Every mutation is also recorded in TenantBrainEntryHistory, mirroring how
tenant_notes_history.set_tenant_notes tracks notes edits.
"""
from __future__ import annotations

import logging
import time
from datetime import date

from sqlalchemy.orm import Session

from app.models.ai_agent_profile import BRAIN_WRITER_ROLE, AiAgentProfile
from app.models.ai_agent_run import STATUS_COMPLETED, STATUS_FAILED, STATUS_SKIPPED, AiAgentRun, AiAgentRunStep
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_brain_entry import SOURCE_MANUAL, SOURCE_PLANNER, SOURCE_SCANNER, TenantBrainEntry
from app.models.tenant_brain_entry_history import (
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_UPDATED,
    TenantBrainEntryHistory,
)
from app.models.tenant_brain_trigger import TenantBrainTrigger
from app.services import (
    action_item_service,
    ai_agent_orchestrator,
    ai_prompt_blocks,
    ai_reply_service,
    brain_field_service,
    gemini_client,
)

logger = logging.getLogger(__name__)

# field_values and action_items use an empty string / omitted key to mean "no evidence" rather
# than a JSON null, since Gemini's structured-output schemas handle plain string properties far
# more reliably than nullable ones - the writer only upserts entries whose value is non-empty.
BRAIN_WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "should_remember": {"type": "boolean"},
        "field_values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "due_date": {"type": "string"},
                },
                "required": ["title"],
            },
        },
        "entries": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["should_remember", "reasoning"],
}

_BRAIN_WRITER_PREAMBLE = (
    "You maintain a long-term memory file about one tenant in a short-stay rental CRM. Decide "
    "whether the latest message reveals something durable worth remembering: a preference, a "
    "recurring issue, a special agreement, a complaint pattern. Routine questions, one-off "
    "logistics, and anything already listed below are not worth adding."
)

_SCANNER_PREAMBLE = (
    "You are scanning a tenant's full history in a short-stay rental CRM to build an initial "
    "long-term memory file. List every durable fact worth remembering going forward: "
    "preferences, recurring issues, special agreements, complaint patterns. Ignore routine "
    "questions and one-off logistics that have no bearing on future interactions."
)

_FIELD_GUARDRAILS = (
    "## Structured Fields\n"
    "Below is the schema of fields this CRM tracks per tenant, each with an instruction for "
    "what evidence to look for, and the tenant's current values. Only include a field in "
    "`field_values` when the message/history gives direct evidence for it - leave it out "
    "entirely (or use an empty string) when you are not sure rather than guessing. Never repeat "
    "a fact in `entries` if it already fits one of these fields."
)

_ACTION_ITEM_GUARDRAILS = (
    "## Action Items\n"
    "Do NOT invent action items. Only add one to `action_items` if the tenant explicitly "
    "requests a task, or a clear operational follow-up is strictly required by this specific "
    "message. When in doubt, leave `action_items` empty."
)

_OUTPUT_INSTRUCTION = (
    "## Output\n"
    "Return JSON only. Set `should_remember` to true only if there is at least one new, durable "
    "fact, field value, or action item worth saving. `field_values` lists only fields you have "
    "direct evidence for (omit the rest). `action_items` lists only genuinely new tasks (see "
    "guardrails above - usually empty). `entries` is a list of short, standalone facts to add "
    "that don't fit a field - empty if should_remember is false. `reasoning` briefly explains "
    "the decision."
)


def list_entries(db: Session, tenant_id: int) -> list[TenantBrainEntry]:
    return (
        db.query(TenantBrainEntry)
        .filter(TenantBrainEntry.tenant_id == tenant_id)
        .order_by(TenantBrainEntry.created_at.desc(), TenantBrainEntry.id.desc())
        .all()
    )


def add_entry(
    db: Session,
    tenant: Tenant,
    content: str,
    source: str,
    changed_by_user_id: int | None = None,
) -> TenantBrainEntry | None:
    content = (content or "").strip()
    if not content:
        return None
    entry = TenantBrainEntry(tenant_id=tenant.id, content=content, source=source)
    db.add(entry)
    db.flush()
    db.add(
        TenantBrainEntryHistory(
            tenant_id=tenant.id,
            entry_id=entry.id,
            action=ACTION_CREATED,
            old_value=None,
            new_value=content,
            source=source,
            changed_by_user_id=changed_by_user_id,
        )
    )
    return entry


def update_entry(
    db: Session,
    entry: TenantBrainEntry,
    new_content: str,
    changed_by_user_id: int | None = None,
) -> TenantBrainEntry:
    new_content = (new_content or "").strip()
    old_content = entry.content
    if old_content == new_content:
        return entry
    entry.content = new_content
    db.add(
        TenantBrainEntryHistory(
            tenant_id=entry.tenant_id,
            entry_id=entry.id,
            action=ACTION_UPDATED,
            old_value=old_content,
            new_value=new_content,
            source=SOURCE_MANUAL,
            changed_by_user_id=changed_by_user_id,
        )
    )
    return entry


def delete_entry(db: Session, entry: TenantBrainEntry, changed_by_user_id: int | None = None) -> None:
    db.add(
        TenantBrainEntryHistory(
            tenant_id=entry.tenant_id,
            entry_id=entry.id,
            action=ACTION_DELETED,
            old_value=entry.content,
            new_value=None,
            source=SOURCE_MANUAL,
            changed_by_user_id=changed_by_user_id,
        )
    )
    db.delete(entry)


def _resolve_history_channels(profile: AiAgentProfile, channel: str) -> str:
    configured = (profile.history_channels or "both").strip()
    if configured == "inbound":
        return channel if channel in ("email", "whatsapp") else "both"
    return configured if configured in ("both", "email", "whatsapp") else "both"


def _existing_entries_block(entries: list[TenantBrainEntry]) -> str:
    if not entries:
        return ai_prompt_blocks.join("## Already Remembered", "Nothing yet.")
    body = "\n".join(f"- {entry.content}" for entry in entries)
    return ai_prompt_blocks.join("## Already Remembered", body)


def _fields_block(db: Session, tenant_id: int) -> str:
    definitions = brain_field_service.list_definitions(db, active_only=True)
    if not definitions:
        return ""
    values = brain_field_service.get_values_for_tenant(db, tenant_id)
    lines = []
    for definition in definitions:
        current = values.get(definition.id)
        current_value = current.value if current is not None and current.value else "(not set)"
        lines.append(f"- key={definition.key} | {definition.label} | look for: {definition.ai_instruction} | current: {current_value}")
    return ai_prompt_blocks.join(_FIELD_GUARDRAILS, "\n".join(lines))


def _build_prompt(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    preamble: str,
    channel: str,
    inbound_text: str | None,
    history_limit: int,
    existing_entries: list[TenantBrainEntry],
) -> str:
    parts: list[str] = [preamble]

    instructions = (profile.instructions or "").strip()
    if instructions:
        parts.append(ai_prompt_blocks.join("## Your Instructions", instructions))

    parts.append(_existing_entries_block(existing_entries))

    fields_block = _fields_block(db, tenant.id)
    if fields_block:
        parts.append(fields_block)
    parts.append(_ACTION_ITEM_GUARDRAILS)

    if history_limit:
        parts.append(
            ai_reply_service._build_history_context(
                db,
                tenant,
                history_limit,
                channels=_resolve_history_channels(profile, channel),
                lookback_days=profile.history_lookback_days,
            )
        )
    if profile.include_beds24:
        parts.append(ai_reply_service._build_beds24_context(tenant))
    if profile.include_payments:
        parts.append(ai_reply_service._build_payments_context(db, tenant))
    if profile.include_notes:
        parts.append(ai_reply_service._build_notes_context(tenant))
    if profile.include_availability:
        parts.append(ai_reply_service._build_availability_context(db))
    if inbound_text:
        parts.append(ai_prompt_blocks.join("## Latest Inbound Message", inbound_text))

    parts.append(_OUTPUT_INSTRUCTION)
    return "\n\n".join(part for part in parts if part.strip())


def _run_brain_writer(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    mode: str,
    channel: str,
    prompt: str,
    source: str,
) -> list[TenantBrainEntry]:
    """One LLM call plus the AiAgentRun bookkeeping, shared by the trigger and scan paths."""
    run = AiAgentRun(
        tenant_id=tenant.id,
        channel=channel,
        mode=mode,
        status=STATUS_FAILED,
        planner_profile_id=profile.id,
    )
    db.add(run)
    db.flush()
    started = time.monotonic()

    try:
        result = gemini_client.generate(
            prompt,
            model=profile.model,
            temperature=profile.temperature,
            max_output_tokens=profile.max_output_tokens,
            response_schema=BRAIN_WRITER_SCHEMA,
        )
    except gemini_client.GeminiClientError as exc:
        db.add(AiAgentRunStep(run_id=run.id, step_index=0, stage="brain_writer", prompt=prompt, error=str(exc), model=profile.model))
        run.status = STATUS_FAILED
        run.duration_ms = int((time.monotonic() - started) * 1000)
        logger.warning("Brain writer call failed tenant_id=%s error=%s", tenant.id, exc)
        return []

    db.add(
        AiAgentRunStep(
            run_id=run.id,
            step_index=0,
            stage="brain_writer",
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
    if not plan.get("should_remember", False):
        run.status = STATUS_SKIPPED
        return []

    added: list[TenantBrainEntry] = []
    for content in plan.get("entries") or []:
        entry = add_entry(db, tenant, str(content), source=source)
        if entry is not None:
            added.append(entry)

    definitions_by_key = {d.key: d for d in brain_field_service.list_definitions(db, active_only=True)}
    for field_value in plan.get("field_values") or []:
        key = str((field_value or {}).get("key") or "").strip()
        value = str((field_value or {}).get("value") or "").strip()
        definition = definitions_by_key.get(key)
        if definition is None or not value:
            continue
        brain_field_service.set_value(db, tenant.id, definition.id, value, source=source)

    for action_item in plan.get("action_items") or []:
        title = str((action_item or {}).get("title") or "").strip()
        if not title:
            continue
        description = str((action_item or {}).get("description") or "").strip() or None
        due_date_raw = str((action_item or {}).get("due_date") or "").strip()
        due_date = None
        if due_date_raw:
            try:
                due_date = date.fromisoformat(due_date_raw)
            except ValueError:
                due_date = None
        action_item_service.create_ai_item(db, tenant.id, title, description, due_date)

    run.status = STATUS_COMPLETED
    return added


def generate_brain_update_for_trigger(db: Session, trigger: TenantBrainTrigger) -> list[TenantBrainEntry]:
    """The automatic path: one due TenantBrainTrigger row, one LLM call, zero or more entries.

    Mirrors ai_auto_draft_service.generate_draft_for_trigger's shape: returns quietly for any
    state that makes generation impossible, so the scheduler sweep can just move on.
    """
    tenant = db.query(Tenant).filter(Tenant.id == trigger.tenant_id).first()
    if tenant is None:
        return []

    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    if ai_settings is None or not ai_settings.brain_writer_enabled:
        return []

    profile = ai_agent_orchestrator.resolve_profile(db, BRAIN_WRITER_ROLE, ai_settings.brain_writer_profile_id)
    if profile is None:
        return []

    inbound_text = ai_agent_orchestrator.latest_inbound_text(db, tenant.id, trigger.channel)
    if not inbound_text:
        return []

    existing_entries = list_entries(db, tenant.id)
    prompt = _build_prompt(
        db,
        tenant,
        profile,
        preamble=_BRAIN_WRITER_PREAMBLE,
        channel=trigger.channel,
        inbound_text=inbound_text,
        history_limit=max(0, int(profile.history_limit or 0)),
        existing_entries=existing_entries,
    )
    return _run_brain_writer(
        db, tenant, profile, mode="brain_writer", channel=trigger.channel, prompt=prompt, source=SOURCE_PLANNER
    )


def scan_tenant_history(db: Session, tenant: Tenant, user_id: int | None = None) -> list[TenantBrainEntry]:
    """The manual "Generate initial brain" path: one large one-off scan, tagged as source=scanner."""
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    profile = ai_agent_orchestrator.resolve_profile(
        db, BRAIN_WRITER_ROLE, ai_settings.brain_writer_profile_id if ai_settings else None
    )
    if profile is None:
        return []

    existing_entries = list_entries(db, tenant.id)
    prompt = _build_prompt(
        db,
        tenant,
        profile,
        preamble=_SCANNER_PREAMBLE,
        channel="both",
        inbound_text=None,
        history_limit=max(200, int(profile.history_limit or 0)),
        existing_entries=existing_entries,
    )
    return _run_brain_writer(db, tenant, profile, mode="brain_scan", channel="both", prompt=prompt, source=SOURCE_SCANNER)
