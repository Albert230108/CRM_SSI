from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_agent_run import AiAgentRun
from app.models.ai_reply_template import AiReplyTemplate
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.ai_agent_run import AiAgentRunDetail, AiAgentRunListRead, AiAgentRunRead

router = APIRouter(prefix="/ai-agent-runs", tags=["ai-agent-runs"])


def _with_tenant_name(db: Session, run: AiAgentRun) -> dict:
    """Runs are listed cross-tenant, so the tenant name is joined in for the UI."""
    name = db.query(Tenant.name).filter(Tenant.id == run.tenant_id).scalar()
    return {"tenant_name": name}


def _template_name_map(db: Session, template_ids: set[int]) -> dict[int, str]:
    """Batch-resolve template ids to names; a missing id (deleted template) is simply absent."""
    if not template_ids:
        return {}
    rows = db.query(AiReplyTemplate.id, AiReplyTemplate.name).filter(AiReplyTemplate.id.in_(template_ids)).all()
    return {template_id: name for template_id, name in rows}


def _alternative_template_ids(run: AiAgentRun) -> set[int]:
    """Template ids the planner considered and rejected, read out of its stored plan JSON."""
    ids: set[int] = set()
    for step in run.steps:
        parsed = step.parsed if isinstance(step.parsed, dict) else None
        for alternative in (parsed or {}).get("alternatives") or []:
            template_id = alternative.get("template_id") if isinstance(alternative, dict) else None
            if isinstance(template_id, int):
                ids.add(template_id)
    return ids


def _redo_display_mode_map(db: Session, runs: list[AiAgentRun]) -> dict[int, str]:
    run_ids = [run.id for run in runs]
    if not run_ids:
        return {}

    matched_logs = (
        db.query(RedoRequestLog)
        .filter(RedoRequestLog.ai_agent_run_id.in_(run_ids))
        .all()
    )
    if not matched_logs:
        return {}

    draft_ids = {log.ai_auto_draft_id for log in matched_logs if log.ai_auto_draft_id is not None}
    if not draft_ids:
        return {}

    history_logs = (
        db.query(RedoRequestLog)
        .filter(RedoRequestLog.ai_auto_draft_id.in_(draft_ids))
        .order_by(RedoRequestLog.ai_auto_draft_id.asc(), RedoRequestLog.created_at.asc(), RedoRequestLog.id.asc())
        .all()
    )
    sequence_by_log_id: dict[int, int] = {}
    draft_sequence_counts: defaultdict[int, int] = defaultdict(int)
    for log in history_logs:
        draft_id = log.ai_auto_draft_id
        if draft_id is None:
            continue
        draft_sequence_counts[draft_id] += 1
        sequence_by_log_id[log.id] = draft_sequence_counts[draft_id]

    log_by_run_id = {log.ai_agent_run_id: log for log in matched_logs if log.ai_agent_run_id is not None}
    display_modes: dict[int, str] = {}
    for run in runs:
        log = log_by_run_id.get(run.id)
        if log is None or log.ai_auto_draft_id is None:
            continue
        sequence = sequence_by_log_id.get(log.id)
        if sequence is not None:
            display_modes[run.id] = f"redo #{sequence}"
    return display_modes


def _run_read(db: Session, run: AiAgentRun, *, display_mode: str | None = None, final_template_name: str | None = None) -> AiAgentRunRead:
    return AiAgentRunRead.model_validate(run).model_copy(
        update={
            **_with_tenant_name(db, run),
            "final_template_name": final_template_name,
            "display_mode": display_mode or run.mode,
        }
    )


@router.get("", response_model=AiAgentRunListRead)
def list_agent_runs(
    tenant_id: int | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAgentRunListRead:
    query = db.query(AiAgentRun)
    if tenant_id is not None:
        query = query.filter(AiAgentRun.tenant_id == tenant_id)
    if status_filter:
        query = query.filter(AiAgentRun.status == status_filter)

    total = query.order_by(None).count()
    runs = query.order_by(AiAgentRun.created_at.desc(), AiAgentRun.id.desc()).offset(offset).limit(limit).all()
    template_names = _template_name_map(
        db, {run.final_template_id for run in runs if run.final_template_id is not None}
    )
    display_modes = _redo_display_mode_map(db, runs)
    items = [
        _run_read(
            db,
            run,
            display_mode=display_modes.get(run.id),
            final_template_name=template_names.get(run.final_template_id),
        )
        for run in runs
    ]
    return AiAgentRunListRead(items=items, total=total)


@router.get("/{run_id}", response_model=AiAgentRunDetail)
def get_agent_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAgentRunDetail:
    run = db.query(AiAgentRun).filter(AiAgentRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")

    template_ids = _alternative_template_ids(run)
    if run.final_template_id is not None:
        template_ids.add(run.final_template_id)
    template_names = _template_name_map(db, template_ids)
    display_mode = _redo_display_mode_map(db, [run]).get(run.id, run.mode)

    return AiAgentRunDetail.model_validate(run).model_copy(
        update={
            **_with_tenant_name(db, run),
            "final_template_name": template_names.get(run.final_template_id),
            "template_names": template_names,
            "display_mode": display_mode,
        }
    )
