"""Decides, independently of the planner and brain writer, whether a tenant's action-item list
needs a new task or a change to an existing one.

New items (`new_items`) are created directly, same as brain_writer entries - surfacing
immediately, no approval needed. Proposed changes to an *existing* item (`modify_items`, `complete_items`, `delete_items`) are never applied directly: they become pending MemorySuggestion rows a human
must approve (see memory_suggestion_service._apply_action_item_modify/_complete/_delete), mirroring how
memory_redo's rule suggestions work.

Runs on its own debounced trigger - see action_writer_trigger_service.py and the scheduler
sweep in main.py. Structurally mirrors tenant_brain_service.py.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date
from datetime import time as time_of_day

from sqlalchemy.orm import Session

from app.models.action_item import ActionItem
from app.models.action_item_tag import ActionItemTag
from app.models.action_tag_definition import ActionTagDefinition
from app.models.action_writer_trigger import ActionWriterTrigger
from app.models.ai_agent_profile import ACTION_WRITER_ROLE, AiAgentProfile
from app.models.ai_agent_run import STATUS_COMPLETED, STATUS_FAILED, STATUS_SKIPPED, AiAgentRun, AiAgentRunStep
from app.models.memory_suggestion import KIND_ACTION_ITEM_COMPLETE, KIND_ACTION_ITEM_DELETE, KIND_ACTION_ITEM_MODIFY, STATUS_PENDING, MemorySuggestion
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import action_item_service, action_tag_service, ai_agent_orchestrator, ai_prompt_blocks, ai_reply_service, gemini_client
from app.services.datetime_placeholders import resolve_datetime_placeholders

logger = logging.getLogger(__name__)

_VALID_PRIORITIES = {"p1", "p2", "p3", "p4"}

ACTION_WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "new_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "ai_instruction": {"type": "string"},
                    "due_date": {"type": "string"},
                    "due_time": {"type": "string"},
                    "priority": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title"],
            },
        },
        "modify_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action_item_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "ai_instruction": {"type": "string"},
                    "due_date": {"type": "string"},
                    "due_time": {"type": "string"},
                    "priority": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "reasoning": {"type": "string"},
                },
                "required": ["action_item_id", "reasoning"],
            },
        },
        "delete_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action_item_id": {"type": "integer"},
                    "reasoning": {"type": "string"},
                },
                "required": ["action_item_id", "reasoning"],
            },
        },
        "complete_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action_item_id": {"type": "integer"},
                    "reasoning": {"type": "string"},
                },
                "required": ["action_item_id", "reasoning"],
            },
        },
        "reasoning": {"type": "string"},
    },
    "required": ["reasoning"],
}

_ACTION_WRITER_PREAMBLE = (
    "You maintain the action-item checklist for one tenant in a short-stay rental CRM. Decide "
    "whether the latest message means a new task should be tracked, or an existing open task "
    "needs to change, be completed, or be removed. Do NOT invent tasks - only add one if the tenant explicitly "
    "requests something, or a clear operational follow-up is strictly required by this specific "
    "message. When in doubt, propose nothing. Treat \"completed\" as the tenant indicating the work was actually done; "
    "treat \"removed\" as the task is no longer needed or relevant."
)

_OPEN_ITEMS_HEADER = "## Open Action Items (id | title | due date/time | priority | tags)"
_TAGS_HEADER = "## Available Tags (choose `tags` from this list only, or omit)"

_OUTPUT_INSTRUCTION = (
    "## Output\n"
    "Return JSON only. `new_items` lists genuinely new tasks - usually empty. `modify_items`, `complete_items`, and `delete_items` reference an existing item's `action_item_id` from the list above and always "
    "include a `reasoning` explaining why the change is warranted - a human reviews these before "
    "they take effect. Use `complete_items` when the tenant's message indicates the task was actually accomplished; use `delete_items` when the task is no longer needed or relevant. `priority` is one of p1 (most urgent) to p4 (least urgent), omit if not "
    "implied. `tags` must be zero or more of the available tag names above, omit if none fits. "
    "`ai_instruction` is an optional short directive for a future AI planner run on this task "
    "(what the reply/action should accomplish), distinct from the human-facing `description`; omit if none is warranted. "
    "`due_time` is an optional time of day for `due_date`, formatted HH:MM (24-hour) - only set it when the message "
    "clearly implies a specific time, omit otherwise. "
    "`reasoning` at the top level briefly explains the overall decision."
)


def _open_items_block(db: Session, tenant_id: int) -> str:
    items = [item for item in action_item_service.list_for_tenant(db, tenant_id) if item.status == "open"]
    if not items:
        return ai_prompt_blocks.join(_OPEN_ITEMS_HEADER, "None yet.")
    item_ids = [item.id for item in items]
    link_rows = (
        db.query(ActionItemTag.action_item_id, ActionItemTag.tag_id)
        .filter(ActionItemTag.action_item_id.in_(item_ids))
        .order_by(ActionItemTag.action_item_id, ActionItemTag.position, ActionItemTag.id)
        .all()
    )
    tag_ids = {tag_id for _, tag_id in link_rows}
    tags_by_id = {tag.id: tag for tag in db.query(ActionTagDefinition).filter(ActionTagDefinition.id.in_(tag_ids)).all()} if tag_ids else {}
    tag_names_by_item_id: dict[int, list[str]] = defaultdict(list)
    for item_id, tag_id in link_rows:
        tag = tags_by_id.get(tag_id)
        if tag is not None:
            tag_names_by_item_id[item_id].append(tag.name)
    lines = [
        f"- id={item.id} | {item.title} | due: "
        f"{f'{item.due_date} {item.due_time}' if item.due_date and item.due_time else (item.due_date or '(none)')} | "
        f"priority: {item.priority or '(none)'} | tags: {', '.join(tag_names_by_item_id.get(item.id, [])) or '(none)'}"
        for item in items
    ]
    return ai_prompt_blocks.join(_OPEN_ITEMS_HEADER, "\n".join(lines))


def _tags_block(db: Session) -> str:
    tags = action_tag_service.list_definitions(db, active_only=True)
    if not tags:
        return ai_prompt_blocks.join(_TAGS_HEADER, "None configured.")
    return ai_prompt_blocks.join(_TAGS_HEADER, "\n".join(f"- {tag.name}" for tag in tags))


def _build_prompt(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    channel: str,
    message_text: str,
    history_limit: int,
) -> str:
    parts: list[str] = [_ACTION_WRITER_PREAMBLE]

    instructions = resolve_datetime_placeholders((profile.instructions or "").strip())
    if instructions:
        parts.append(ai_prompt_blocks.join("## Your Instructions", instructions))

    parts.append(_open_items_block(db, tenant.id))
    parts.append(_tags_block(db))

    if history_limit:
        parts.append(
            ai_reply_service._build_history_context(
                db,
                tenant,
                history_limit,
                channels=channel if channel in ("email", "whatsapp") else "both",
                lookback_days=profile.history_lookback_days,
            )
        )
    if profile.include_beds24:
        parts.append(ai_reply_service._build_beds24_context(tenant))
    if profile.include_notes:
        parts.append(ai_reply_service._build_notes_context(tenant))
    if profile.include_payments:
        parts.append(ai_reply_service._build_payments_context(db, tenant))
    if message_text:
        parts.append(ai_prompt_blocks.join("## Latest Message", message_text))

    parts.append(_OUTPUT_INSTRUCTION)
    return "\n\n".join(part for part in parts if part.strip())


def _resolve_priority(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    return value if value in _VALID_PRIORITIES else None


def _resolve_due_date(raw: str | None) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _resolve_due_time(raw: str | None) -> time_of_day | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return time_of_day.fromisoformat(value)
    except ValueError:
        return None


def _suggestion_exists(db: Session, *, kind: str, target_id: int) -> bool:
    """Avoids spamming a duplicate pending suggestion for the same item every time the debounced
    trigger fires again before a human has reviewed the first one."""
    return (
        db.query(MemorySuggestion.id)
        .filter(MemorySuggestion.kind == kind, MemorySuggestion.target_id == target_id, MemorySuggestion.status == STATUS_PENDING)
        .first()
        is not None
    )


def _apply_plan(db: Session, tenant: Tenant, plan: dict) -> tuple[int, int, int, int]:
    new_items_written = 0
    modify_suggestions_written = 0
    delete_suggestions_written = 0
    complete_suggestions_written = 0

    for raw_item in plan.get("new_items") or []:
        title = str((raw_item or {}).get("title") or "").strip()
        if not title:
            continue
        description = str((raw_item or {}).get("description") or "").strip() or None
        ai_instruction = str((raw_item or {}).get("ai_instruction") or "").strip() or None
        action_item_service.create_ai_item(
            db,
            tenant.id,
            title,
            description,
            _resolve_due_date((raw_item or {}).get("due_date")),
            ai_instruction=ai_instruction,
            due_time=_resolve_due_time((raw_item or {}).get("due_time")),
            tag_ids=action_tag_service.resolve_tag_ids(db, (raw_item or {}).get("tags")),
            priority=_resolve_priority((raw_item or {}).get("priority")),
        )
        new_items_written += 1

    open_item_ids = {item.id for item in action_item_service.list_for_tenant(db, tenant.id) if item.status == "open"}

    for raw_item in plan.get("modify_items") or []:
        item_id = (raw_item or {}).get("action_item_id")
        if not isinstance(item_id, int) or item_id not in open_item_ids:
            continue
        if _suggestion_exists(db, kind=KIND_ACTION_ITEM_MODIFY, target_id=item_id):
            continue
        proposed_value: dict = {}
        title = str((raw_item or {}).get("title") or "").strip()
        if title:
            proposed_value["title"] = title
        ai_instruction = str((raw_item or {}).get("ai_instruction") or "").strip()
        if ai_instruction:
            proposed_value["ai_instruction"] = ai_instruction
        due_date = _resolve_due_date((raw_item or {}).get("due_date"))
        if due_date is not None:
            proposed_value["due_date"] = due_date.isoformat()
        due_time = _resolve_due_time((raw_item or {}).get("due_time"))
        if due_time is not None:
            proposed_value["due_time"] = due_time.isoformat()
        priority = _resolve_priority((raw_item or {}).get("priority"))
        if priority is not None:
            proposed_value["priority"] = priority
        tag_ids = action_tag_service.resolve_tag_ids(db, (raw_item or {}).get("tags"))
        if tag_ids:
            proposed_value["tag_ids"] = tag_ids
        if not proposed_value:
            continue
        db.add(
            MemorySuggestion(
                kind=KIND_ACTION_ITEM_MODIFY,
                tenant_id=tenant.id,
                target_id=item_id,
                proposed_value=proposed_value,
                reasoning=str((raw_item or {}).get("reasoning") or "").strip() or None,
                status=STATUS_PENDING,
            )
        )
        modify_suggestions_written += 1

    for raw_item in plan.get("complete_items") or []:
        item_id = (raw_item or {}).get("action_item_id")
        if not isinstance(item_id, int) or item_id not in open_item_ids:
            continue
        if _suggestion_exists(db, kind=KIND_ACTION_ITEM_COMPLETE, target_id=item_id):
            continue
        db.add(
            MemorySuggestion(
                kind=KIND_ACTION_ITEM_COMPLETE,
                tenant_id=tenant.id,
                target_id=item_id,
                proposed_value={},
                reasoning=str((raw_item or {}).get("reasoning") or "").strip() or None,
                status=STATUS_PENDING,
            )
        )
        complete_suggestions_written += 1

    for raw_item in plan.get("delete_items") or []:
        item_id = (raw_item or {}).get("action_item_id")
        if not isinstance(item_id, int) or item_id not in open_item_ids:
            continue
        if _suggestion_exists(db, kind=KIND_ACTION_ITEM_DELETE, target_id=item_id):
            continue
        db.add(
            MemorySuggestion(
                kind=KIND_ACTION_ITEM_DELETE,
                tenant_id=tenant.id,
                target_id=item_id,
                proposed_value={},
                reasoning=str((raw_item or {}).get("reasoning") or "").strip() or None,
                status=STATUS_PENDING,
            )
        )
        delete_suggestions_written += 1

    return new_items_written, modify_suggestions_written, complete_suggestions_written, delete_suggestions_written


def generate_action_writer_update_for_trigger(db: Session, trigger: ActionWriterTrigger) -> None:
    """The automatic path: one due ActionWriterTrigger row, one LLM call, zero or more new
    items created plus zero or more pending modify/complete/delete suggestions.

    Mirrors tenant_brain_service.generate_brain_update_for_trigger's shape: returns quietly for
    any state that makes generation impossible, so the scheduler sweep can just move on.
    """
    tenant = db.query(Tenant).filter(Tenant.id == trigger.tenant_id).first()
    if tenant is None:
        return

    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    if ai_settings is None or not ai_settings.action_writer_enabled:
        return

    profile = ai_agent_orchestrator.resolve_profile(db, ACTION_WRITER_ROLE, ai_settings.action_writer_profile_id)
    if profile is None:
        return

    message_text = ai_agent_orchestrator.latest_message_text(db, tenant.id, trigger.channel)
    if not message_text:
        return

    prompt = _build_prompt(
        db,
        tenant,
        profile,
        channel=trigger.channel,
        message_text=message_text,
        history_limit=max(0, int(profile.history_limit or 0)),
    )

    run = AiAgentRun(tenant_id=tenant.id, channel=trigger.channel, mode="action_writer", status=STATUS_FAILED, planner_profile_id=profile.id)
    db.add(run)
    db.flush()
    started = time.monotonic()

    try:
        result = gemini_client.generate(
            prompt,
            model=profile.model,
            temperature=profile.temperature,
            max_output_tokens=profile.max_output_tokens,
            response_schema=ACTION_WRITER_SCHEMA,
        )
    except gemini_client.GeminiClientError as exc:
        db.add(AiAgentRunStep(run_id=run.id, step_index=0, stage="action_writer", prompt=prompt, error=str(exc), model=profile.model))
        run.status = STATUS_FAILED
        run.duration_ms = int((time.monotonic() - started) * 1000)
        logger.warning("Action writer call failed tenant_id=%s error=%s", tenant.id, exc)
        return

    db.add(
        AiAgentRunStep(
            run_id=run.id,
            step_index=0,
            stage="action_writer",
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
    has_changes = bool(plan.get("new_items") or plan.get("modify_items") or plan.get("complete_items") or plan.get("delete_items"))
    if not has_changes:
        run.status = STATUS_SKIPPED
        return

    new_items_written, modify_suggestions_written, complete_suggestions_written, delete_suggestions_written = _apply_plan(db, tenant, plan)
    run.status = STATUS_COMPLETED
    logger.info(
        "Action writer run completed run_id=%s tenant_id=%s new_items_written=%s modify_suggestions_written=%s complete_suggestions_written=%s delete_suggestions_written=%s",
        run.id,
        tenant.id,
        new_items_written,
        modify_suggestions_written,
        complete_suggestions_written,
        delete_suggestions_written,
    )
