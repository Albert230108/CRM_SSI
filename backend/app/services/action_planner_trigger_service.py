"""Fires the planner (draft-a-reply loop) for a single action item once it comes due.

An open, tenant-bound action with a due date carrying at least one active tag flagged
`triggers_planner` runs the planner for its tenant when its due date/time passes. General
(tenant-less) items never trigger. The draft channel is the tenant's most recent conversation.
The action's own fields (title, description, ai_instruction, tags, created_at, due date+time) are
handed to the planner as the operator note - run_planner_loop already threads operator_note into
its prompt.

Fire-once-per-due-change: `planner_triggered_at` is stamped before the run so the 15s scheduler
sweep (main.py) cannot re-fire it every tick; action_item_service.update clears it when the due
date/time change. Editing the due date/time is therefore the way to re-arm a trigger.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.api.tenants import compute_last_message_by_tenant_id
from app.models.action_item import STATUS_OPEN, ActionItem
from app.models.action_tag_definition import ActionTagDefinition
from app.models.ai_auto_draft import AiAutoDraft
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import action_tag_service
from app.services.ai_plan_execution_service import run_ai_plan_for_draft
from app.services.bulk_planner_schedule_service import _channel_is_eligible

logger = logging.getLogger(__name__)

# Matches the bulk planner's timezone. A due action with no explicit time fires at this local time.
_LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
DEFAULT_DUE_TIME_LOCAL = time(9, 0)


def _due_instant_utc(item: ActionItem) -> datetime:
    local_time = item.due_time or DEFAULT_DUE_TIME_LOCAL
    local_dt = datetime.combine(item.due_date, local_time).replace(tzinfo=_LOCAL_TZ)
    return local_dt.astimezone(timezone.utc)


def _build_operator_note(db: Session, item: ActionItem) -> str:
    tag_names = []
    if item.tag_ids:
        tags = {tag.id: tag.name for tag in action_tag_service.list_definitions(db)}
        tag_names = [tags[tag_id] for tag_id in item.tag_ids if tag_id in tags]
    due_time = item.due_time.strftime("%H:%M") if item.due_time else DEFAULT_DUE_TIME_LOCAL.strftime("%H:%M")
    lines = [
        "This planner run was triggered by a due action item. Draft a reply that addresses it.",
        f"Title: {item.title}",
    ]
    if item.description:
        lines.append(f"Description: {item.description}")
    if item.ai_instruction:
        lines.append(f"Instruction: {item.ai_instruction}")
    if tag_names:
        lines.append(f"Labels: {', '.join(tag_names)}")
    lines.append(f"Created: {item.created_at.isoformat()}")
    lines.append(f"Due: {item.due_date.isoformat()} {due_time}")
    return "\n".join(lines)


def _process_due_item(db: Session, item: ActionItem, now: datetime) -> None:
    # Claim the item before doing any work so a crash mid-run cannot re-fire it every tick.
    item.planner_triggered_at = now
    db.commit()

    tenant_id = item.tenant_id
    last_message = compute_last_message_by_tenant_id(db, [tenant_id]).get(tenant_id)
    if last_message is None:
        logger.info("Action planner trigger skipped item_id=%s: no conversation history", item.id)
        return
    _occurred_at, channel, _direction = last_message

    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    eligible, skip_reason = _channel_is_eligible(ai_settings, channel)
    if not eligible:
        logger.info("Action planner trigger skipped item_id=%s channel=%s: %s", item.id, channel, skip_reason)
        return

    operator_note = _build_operator_note(db, item)

    draft = AiAutoDraft(tenant_id=tenant_id, channel=channel, generated_text="", status="pending", scheduled_send_at=None)
    db.add(draft)
    db.commit()
    db.refresh(draft)

    run_ai_plan_for_draft(
        db,
        draft_id=draft.id,
        tenant_id=tenant_id,
        channel=channel,
        operator_note=operator_note,
        attachment_ids=[],
        user_id=None,
    )
    logger.info("Action planner trigger fired item_id=%s tenant_id=%s channel=%s draft_id=%s", item.id, tenant_id, channel, draft.id)


def run_due_action_planner_triggers(db: Session) -> None:
    now = datetime.now(timezone.utc)

    trigger_tag_ids = {
        row[0]
        for row in db.query(ActionTagDefinition.id)
        .filter(ActionTagDefinition.is_active.is_(True), ActionTagDefinition.triggers_planner.is_(True))
        .all()
    }
    if not trigger_tag_ids:
        return

    candidates = (
        db.query(ActionItem)
        .filter(
            ActionItem.status == STATUS_OPEN,
            ActionItem.tenant_id.isnot(None),
            ActionItem.due_date.isnot(None),
            ActionItem.planner_triggered_at.is_(None),
        )
        .all()
    )

    for item in candidates:
        if trigger_tag_ids.isdisjoint(item.tag_ids):
            continue
        if _due_instant_utc(item) > now:
            continue
        item_id = item.id
        try:
            _process_due_item(db, item, now)
        except Exception:
            db.rollback()
            logger.exception("Action planner trigger failed item_id=%s", item_id)
