from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.bulk_planner_schedule import BulkPlannerSchedule
from app.models.bulk_planner_schedule_run import BulkPlannerScheduleRun
from app.models.bulk_planner_schedule_run_result import BulkPlannerScheduleRunResult
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.bulk_planner_schedule import (
    BulkPlannerPreviewTenant,
    BulkPlannerScheduleCreate,
    BulkPlannerSchedulePreviewResponse,
    BulkPlannerScheduleRead,
    BulkPlannerScheduleRunListRead,
    BulkPlannerScheduleRunRead,
    BulkPlannerScheduleRunResultRead,
    BulkPlannerScheduleUpdate,
)
from app.services import bulk_planner_schedule_service

router = APIRouter(prefix="/bulk-planner-schedules", tags=["bulk-planner-schedules"])

PREVIEW_LIMIT = 12


def _serialize_schedule(
    schedule: BulkPlannerSchedule,
    *,
    last_run: BulkPlannerScheduleRun | None = None,
) -> BulkPlannerScheduleRead:
    return BulkPlannerScheduleRead.model_validate(schedule).model_copy(
        update={
            "status_filter": list(schedule.status_filter or []),
            "last_matched_tenant_count": (last_run.matched_tenant_count if last_run is not None else None),
            "last_run_status": (last_run.status if last_run is not None else None),
            "last_trigger_reason": (last_run.trigger_reason if last_run is not None else None),
        }
    )


def _get_schedule(db: Session, schedule_id: int) -> BulkPlannerSchedule:
    schedule = db.query(BulkPlannerSchedule).filter(BulkPlannerSchedule.id == schedule_id).first()
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return schedule


def _latest_run_by_schedule_id(db: Session, schedule_ids: list[int]) -> dict[int, BulkPlannerScheduleRun]:
    if not schedule_ids:
        return {}
    rows = (
        db.query(BulkPlannerScheduleRun)
        .filter(BulkPlannerScheduleRun.schedule_id.in_(schedule_ids))
        .order_by(BulkPlannerScheduleRun.id.desc())
        .all()
    )
    latest: dict[int, BulkPlannerScheduleRun] = {}
    for row in rows:
        latest.setdefault(row.schedule_id, row)
    return latest


@router.post("", response_model=BulkPlannerScheduleRead, status_code=status.HTTP_201_CREATED)
def create_bulk_planner_schedule(
    payload: BulkPlannerScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkPlannerScheduleRead:
    schedule = BulkPlannerSchedule(
        name=payload.name.strip(),
        enabled=payload.enabled,
        run_time_local=payload.run_time_local,
        status_filter=list(payload.status_filter or []),
        last_message_within_days=payload.last_message_within_days,
        last_message_direction=payload.last_message_direction,
        next_run_at=bulk_planner_schedule_service.compute_next_run_at_utc(payload.run_time_local),
        created_by_user_id=current_user.id,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return _serialize_schedule(schedule)


@router.post("/preview", response_model=BulkPlannerSchedulePreviewResponse)
def preview_bulk_planner_schedule(
    payload: BulkPlannerScheduleCreate | BulkPlannerScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkPlannerSchedulePreviewResponse:
    preview_schedule = BulkPlannerSchedule(
        name=(getattr(payload, "name", None) or "Preview").strip() or "Preview",
        enabled=True if getattr(payload, "enabled", None) is None else bool(getattr(payload, "enabled")),
        run_time_local=getattr(payload, "run_time_local", None) or datetime.min.time(),
        status_filter=list(getattr(payload, "status_filter", None) or []),
        last_message_within_days=getattr(payload, "last_message_within_days", None),
        last_message_direction=getattr(payload, "last_message_direction", None),
        next_run_at=bulk_planner_schedule_service.compute_next_run_at_utc(getattr(payload, "run_time_local", None) or datetime.min.time()),
    )
    tenant_ids = bulk_planner_schedule_service.find_matching_tenant_ids(db, preview_schedule)
    tenants = (
        db.query(Tenant)
        .filter(Tenant.id.in_(tenant_ids[:PREVIEW_LIMIT]))
        .order_by(Tenant.name.asc(), Tenant.id.asc())
        .all()
        if tenant_ids
        else []
    )
    return BulkPlannerSchedulePreviewResponse(
        matched_tenant_count=len(tenant_ids),
        tenants=[BulkPlannerPreviewTenant.model_validate(tenant) for tenant in tenants],
    )


@router.get("", response_model=list[BulkPlannerScheduleRead])
def list_bulk_planner_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BulkPlannerScheduleRead]:
    schedules = (
        db.query(BulkPlannerSchedule)
        .order_by(BulkPlannerSchedule.created_at.desc(), BulkPlannerSchedule.id.desc())
        .all()
    )
    latest_runs = _latest_run_by_schedule_id(db, [schedule.id for schedule in schedules])
    return [_serialize_schedule(schedule, last_run=latest_runs.get(schedule.id)) for schedule in schedules]


@router.get("/{schedule_id}", response_model=BulkPlannerScheduleRead)
def get_bulk_planner_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkPlannerScheduleRead:
    schedule = _get_schedule(db, schedule_id)
    latest_run = (
        db.query(BulkPlannerScheduleRun)
        .filter(BulkPlannerScheduleRun.schedule_id == schedule.id)
        .order_by(BulkPlannerScheduleRun.id.desc())
        .first()
    )
    return _serialize_schedule(schedule, last_run=latest_run)


@router.patch("/{schedule_id}", response_model=BulkPlannerScheduleRead)
def update_bulk_planner_schedule(
    schedule_id: int,
    payload: BulkPlannerScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkPlannerScheduleRead:
    schedule = _get_schedule(db, schedule_id)
    updates = payload.model_dump(exclude_unset=True)

    if "name" in updates:
        schedule.name = (updates["name"] or "").strip()
    if "enabled" in updates:
        schedule.enabled = bool(updates["enabled"])
    if "status_filter" in updates:
        schedule.status_filter = list(updates["status_filter"] or [])
    if "last_message_within_days" in updates:
        schedule.last_message_within_days = updates["last_message_within_days"]
    if "last_message_direction" in updates:
        schedule.last_message_direction = updates["last_message_direction"]
    if "run_time_local" in updates:
        schedule.run_time_local = updates["run_time_local"]
        schedule.next_run_at = bulk_planner_schedule_service.compute_next_run_at_utc(schedule.run_time_local)

    db.commit()
    db.refresh(schedule)
    latest_run = (
        db.query(BulkPlannerScheduleRun)
        .filter(BulkPlannerScheduleRun.schedule_id == schedule.id)
        .order_by(BulkPlannerScheduleRun.id.desc())
        .first()
    )
    return _serialize_schedule(schedule, last_run=latest_run)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bulk_planner_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    schedule = _get_schedule(db, schedule_id)
    db.delete(schedule)
    db.commit()


@router.get("/{schedule_id}/runs", response_model=BulkPlannerScheduleRunListRead)
def list_bulk_planner_schedule_runs(
    schedule_id: int,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkPlannerScheduleRunListRead:
    _get_schedule(db, schedule_id)
    query = db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.schedule_id == schedule_id)
    total = query.order_by(None).count()
    items = (
        query.order_by(BulkPlannerScheduleRun.started_at.desc(), BulkPlannerScheduleRun.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return BulkPlannerScheduleRunListRead(
        total=total,
        items=[BulkPlannerScheduleRunRead.model_validate(item) for item in items],
    )


@router.get("/{schedule_id}/runs/{run_id}/results", response_model=list[BulkPlannerScheduleRunResultRead])
def list_bulk_planner_schedule_run_results(
    schedule_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BulkPlannerScheduleRunResultRead]:
    _get_schedule(db, schedule_id)
    run = (
        db.query(BulkPlannerScheduleRun)
        .filter(BulkPlannerScheduleRun.id == run_id, BulkPlannerScheduleRun.schedule_id == schedule_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    results = (
        db.query(BulkPlannerScheduleRunResult)
        .filter(BulkPlannerScheduleRunResult.run_id == run_id)
        .order_by(BulkPlannerScheduleRunResult.id.asc())
        .all()
    )
    tenant_name_by_id = {
        tenant.id: tenant.name
        for tenant in db.query(Tenant).filter(Tenant.id.in_([row.tenant_id for row in results])).all()
    }
    return [
        BulkPlannerScheduleRunResultRead.model_validate(row).model_copy(
            update={"tenant_name": tenant_name_by_id.get(row.tenant_id)}
        )
        for row in results
    ]
