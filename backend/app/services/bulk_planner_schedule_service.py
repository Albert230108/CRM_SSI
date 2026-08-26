from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.api.tenants import compute_last_message_by_tenant_id
from app.models.ai_auto_draft import AiAutoDraft
from app.models.bulk_planner_schedule import BulkPlannerSchedule
from app.models.bulk_planner_schedule_run import BulkPlannerScheduleRun
from app.models.bulk_planner_schedule_run_result import BulkPlannerScheduleRunResult
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services.ai_plan_execution_service import run_ai_plan_for_draft

logger = logging.getLogger(__name__)

APP_TIMEZONE = ZoneInfo("Europe/Amsterdam")
SCHEDULE_CHANNELS = ("email", "whatsapp")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _localize_schedule_time(target_date: date, run_time_local: time) -> datetime:
    naive_local = datetime.combine(target_date, run_time_local)
    return naive_local.replace(tzinfo=APP_TIMEZONE)


def compute_next_run_at_utc(run_time_local: time, *, now: datetime | None = None) -> datetime:
    current_utc = _ensure_aware_utc(now or _utc_now())
    current_local = current_utc.astimezone(APP_TIMEZONE)
    target_local = _localize_schedule_time(current_local.date(), run_time_local)
    if target_local <= current_local:
        target_local = _localize_schedule_time(current_local.date() + timedelta(days=1), run_time_local)
    return target_local.astimezone(timezone.utc)


def advance_next_run_at_utc(current_next_run_at: datetime, run_time_local: time, *, now: datetime | None = None) -> datetime:
    current_utc = _ensure_aware_utc(now or _utc_now())
    next_local = _ensure_aware_utc(current_next_run_at).astimezone(APP_TIMEZONE)
    candidate_local = _localize_schedule_time(next_local.date() + timedelta(days=1), run_time_local)
    while candidate_local.astimezone(timezone.utc) <= current_utc:
        candidate_local = _localize_schedule_time(candidate_local.date() + timedelta(days=1), run_time_local)
    return candidate_local.astimezone(timezone.utc)


def find_matching_tenant_ids(db: Session, schedule: BulkPlannerSchedule) -> list[int]:
    query = db.query(Tenant)
    status_filter = [value for value in (schedule.status_filter or []) if isinstance(value, str) and value.strip()]
    if status_filter:
        query = query.filter(Tenant.booking_status.in_(status_filter))

    tenants = query.order_by(Tenant.id.asc()).all()
    tenant_ids = [tenant.id for tenant in tenants]
    if not tenant_ids:
        return []

    needs_last_message_lookup = (
        schedule.last_message_within_days is not None or schedule.last_message_direction is not None
    )
    if not needs_last_message_lookup:
        return tenant_ids

    last_message_by_tenant_id = compute_last_message_by_tenant_id(db, tenant_ids)
    cutoff = None
    if schedule.last_message_within_days is not None:
        cutoff = _utc_now() - timedelta(days=schedule.last_message_within_days)

    matched: list[int] = []
    direction_filter = schedule.last_message_direction
    for tenant_id in tenant_ids:
        last_message = last_message_by_tenant_id.get(tenant_id)
        if last_message is None:
            continue
        occurred_at, _channel, direction = last_message
        occurred_at = _ensure_aware_utc(occurred_at)
        if cutoff is not None and occurred_at < cutoff:
            continue
        if direction_filter not in (None, "either") and direction != direction_filter:
            continue
        matched.append(tenant_id)
    return matched


def _channel_is_eligible(ai_settings: TenantAiSettings | None, channel: str) -> tuple[bool, str | None]:
    if ai_settings is None:
        return False, "No AI settings configured for this tenant."
    if (ai_settings.planner_mode or "off") == "off":
        return False, "Planner mode is off for this tenant."
    if channel == "email" and not ai_settings.auto_draft_email:
        return False, "auto_draft_email is disabled for this tenant."
    if channel == "whatsapp" and not ai_settings.auto_draft_whatsapp:
        return False, "auto_draft_whatsapp is disabled for this tenant."
    return True, None


def execute_due_schedule(
    db: Session, schedule: BulkPlannerSchedule, *, trigger_reason: str
) -> BulkPlannerScheduleRun:
    now = _utc_now()
    schedule_id = schedule.id
    run = BulkPlannerScheduleRun(schedule_id=schedule_id, trigger_reason=trigger_reason, status="running")
    db.add(run)
    db.flush()
    run_id = run.id

    # The app already assumes a single process for its other background loops. This follows the
    # same pattern and advances next_run_at before work begins so a later tick in this process
    # cannot re-fire the same schedule while this run is still in progress.
    schedule.next_run_at = advance_next_run_at_utc(schedule.next_run_at, schedule.run_time_local, now=now)
    db.commit()
    db.refresh(schedule)
    db.refresh(run)

    try:
        matched_tenant_ids = find_matching_tenant_ids(db, schedule)
    except Exception as exc:
        db.rollback()
        run = db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.id == run_id).first()
        if run is not None:
            run.completed_at = _utc_now()
            run.status = "failed"
            run.matched_tenant_count = 0
            db.commit()
            db.refresh(run)
        logger.exception("Bulk planner schedule matching failed schedule_id=%s", schedule_id)
        raise

    run = db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.id == run_id).first()
    schedule = db.query(BulkPlannerSchedule).filter(BulkPlannerSchedule.id == schedule_id).first()
    if run is None or schedule is None:
        raise RuntimeError("Bulk planner schedule run disappeared during execution")

    run.matched_tenant_count = len(matched_tenant_ids)
    if matched_tenant_ids:
        settings_by_tenant_id = {
            row.tenant_id: row
            for row in db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id.in_(matched_tenant_ids)).all()
        }
    else:
        settings_by_tenant_id = {}

    for tenant_id in matched_tenant_ids:
        ai_settings = settings_by_tenant_id.get(tenant_id)
        for channel in SCHEDULE_CHANNELS:
            eligible, skip_reason = _channel_is_eligible(ai_settings, channel)
            if not eligible:
                db.add(
                    BulkPlannerScheduleRunResult(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        channel=channel,
                        outcome="skipped",
                        skip_reason=skip_reason,
                    )
                )
                db.commit()
                continue

            draft = AiAutoDraft(
                tenant_id=tenant_id,
                channel=channel,
                generated_text="",
                status="pending",
                scheduled_send_at=None,
            )
            db.add(draft)
            db.commit()
            db.refresh(draft)
            draft_id = draft.id

            try:
                run_ai_plan_for_draft(
                    db,
                    draft_id=draft_id,
                    tenant_id=tenant_id,
                    channel=channel,
                    operator_note=None,
                    attachment_ids=[],
                    user_id=None,
                )
            except Exception as exc:
                db.rollback()
                db.add(
                    BulkPlannerScheduleRunResult(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        channel=channel,
                        outcome="error",
                        error_message=str(exc)[:2000],
                        draft_id=draft_id,
                    )
                )
                db.commit()
                logger.exception(
                    "Bulk planner execution failed schedule_id=%s run_id=%s tenant_id=%s channel=%s",
                    schedule_id,
                    run_id,
                    tenant_id,
                    channel,
                )
                continue

            db.add(
                BulkPlannerScheduleRunResult(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    channel=channel,
                    outcome="success",
                    draft_id=draft_id,
                )
            )
            db.commit()

    run = db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.id == run_id).first()
    schedule = db.query(BulkPlannerSchedule).filter(BulkPlannerSchedule.id == schedule_id).first()
    if run is None or schedule is None:
        raise RuntimeError("Bulk planner schedule run disappeared before completion")

    run.completed_at = _utc_now()
    run.status = "completed"
    schedule.last_run_at = run.completed_at
    db.commit()
    db.refresh(run)
    return run
