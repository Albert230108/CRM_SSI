from collections import defaultdict
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_agent_run import AiAgentRun, AiAgentRunStep
from app.models.ai_model_pricing import AiModelPricing
from app.models.ai_reply_template import AiReplyTemplate
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.ai_agent_run import AiAgentRunDetail, AiAgentRunListRead, AiAgentRunRead, AiAgentRunStatsRead, AiModelUsageStat
from app.services import run_qa_service

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


def _costs_by_run(db: Session, run_ids: list[int]) -> dict[int, tuple[float | None, bool]]:
    """Per-run (total_cost, pricing_missing), mirroring the /stats cost math but scoped per run."""
    if not run_ids:
        return {}
    rows = (
        db.query(
            AiAgentRunStep.run_id,
            AiAgentRunStep.model,
            func.coalesce(func.sum(AiAgentRunStep.prompt_tokens), 0),
            func.coalesce(func.sum(AiAgentRunStep.output_tokens), 0),
        )
        .filter(AiAgentRunStep.run_id.in_(run_ids))
        .filter(AiAgentRunStep.model.isnot(None))
        .group_by(AiAgentRunStep.run_id, AiAgentRunStep.model)
        .all()
    )
    pricing_by_model = {row.model: row for row in db.query(AiModelPricing).all()}

    cost_by_run: dict[int, float] = defaultdict(float)
    has_priced_tokens: dict[int, bool] = defaultdict(bool)
    missing_by_run: dict[int, bool] = defaultdict(bool)
    for run_id, model_name, prompt_tokens_raw, output_tokens_raw in rows:
        prompt_tokens = int(prompt_tokens_raw or 0)
        output_tokens = int(output_tokens_raw or 0)
        if prompt_tokens + output_tokens == 0:
            continue
        pricing = pricing_by_model.get(model_name)
        if pricing is None:
            missing_by_run[run_id] = True
            continue
        input_cost = float(pricing.input_cost_per_million_tokens) * prompt_tokens / 1_000_000
        output_cost = float(pricing.output_cost_per_million_tokens) * output_tokens / 1_000_000
        cost_by_run[run_id] += input_cost + output_cost
        has_priced_tokens[run_id] = True

    return {
        run_id: (cost_by_run.get(run_id) if has_priced_tokens.get(run_id) else None, missing_by_run.get(run_id, False))
        for run_id in set(cost_by_run) | set(missing_by_run)
    }


def _run_read(db: Session, run: AiAgentRun, *, display_mode: str | None = None, final_template_name: str | None = None, total_cost: float | None = None, pricing_missing: bool = False) -> AiAgentRunRead:
    return AiAgentRunRead.model_validate(run).model_copy(
        update={
            **_with_tenant_name(db, run),
            "final_template_name": final_template_name,
            "display_mode": display_mode or run.mode,
            "total_cost": total_cost,
            "pricing_missing": pricing_missing,
        }
    )


def _period_start(period: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if period == "today":
        return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    if period == "month":
        return datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    return None


@router.get("/stats", response_model=AiAgentRunStatsRead)
def get_agent_run_stats(
    period: str = Query("all", pattern="^(all|today|month)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAgentRunStatsRead:
    start_at = _period_start(period)

    run_query = db.query(AiAgentRun)
    step_query = db.query(AiAgentRunStep)
    if start_at is not None:
        run_query = run_query.filter(AiAgentRun.created_at >= start_at)
        step_query = step_query.filter(AiAgentRunStep.created_at >= start_at)

    total_runs = run_query.order_by(None).count()

    rows = (
        step_query.with_entities(
            AiAgentRunStep.model,
            func.coalesce(func.sum(AiAgentRunStep.prompt_tokens), 0),
            func.coalesce(func.sum(AiAgentRunStep.output_tokens), 0),
        )
        .filter(AiAgentRunStep.model.isnot(None))
        .group_by(AiAgentRunStep.model)
        .order_by(AiAgentRunStep.model.asc())
        .all()
    )
    pricing_by_model = {row.model: row for row in db.query(AiModelPricing).all()}

    by_model: list[AiModelUsageStat] = []
    total_prompt_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    any_pricing_missing = False

    for model_name, prompt_tokens_raw, output_tokens_raw in rows:
        prompt_tokens = int(prompt_tokens_raw or 0)
        output_tokens = int(output_tokens_raw or 0)
        total_tokens = prompt_tokens + output_tokens
        if total_tokens == 0:
            continue
        total_prompt_tokens += prompt_tokens
        total_output_tokens += output_tokens

        pricing = pricing_by_model.get(model_name)
        if pricing is None:
            any_pricing_missing = True
            by_model.append(
                AiModelUsageStat(
                    model=model_name,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    pricing_missing=True,
                )
            )
            continue

        input_cost = float(pricing.input_cost_per_million_tokens) * prompt_tokens / 1_000_000
        output_cost = float(pricing.output_cost_per_million_tokens) * output_tokens / 1_000_000
        model_total_cost = input_cost + output_cost
        total_cost += model_total_cost
        by_model.append(
            AiModelUsageStat(
                model=model_name,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                input_cost=input_cost,
                output_cost=output_cost,
                total_cost=model_total_cost,
            )
        )

    return AiAgentRunStatsRead(
        period=period,
        total_runs=total_runs,
        total_prompt_tokens=total_prompt_tokens,
        total_output_tokens=total_output_tokens,
        total_tokens=total_prompt_tokens + total_output_tokens,
        total_cost=None if not by_model else total_cost,
        any_pricing_missing=any_pricing_missing,
        by_model=by_model,
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
    costs_by_run = _costs_by_run(db, [run.id for run in runs])
    items = [
        _run_read(
            db,
            run,
            display_mode=display_modes.get(run.id),
            final_template_name=template_names.get(run.final_template_id),
            total_cost=costs_by_run.get(run.id, (None, False))[0],
            pricing_missing=costs_by_run.get(run.id, (None, False))[1],
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


class RunQaMessageRead(BaseModel):
    id: int
    qa_run_id: int | None = None
    role: str
    content: str
    created_at: datetime


class RunQaContextRead(BaseModel):
    run_summary: str
    instructions: str
    qa_preamble: str
    model: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    run_log_text: str


class RunQaAskRequest(BaseModel):
    question: str


def _get_run_or_404(db: Session, run_id: int) -> AiAgentRun:
    run = db.query(AiAgentRun).filter(AiAgentRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    return run


@router.get("/{run_id}/qa/context", response_model=RunQaContextRead)
def get_run_qa_context(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_run_or_404(db, run_id)
    return run_qa_service.get_context(db, run)


@router.get("/{run_id}/qa", response_model=list[RunQaMessageRead])
def list_run_qa_history(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_run_or_404(db, run_id)
    return run_qa_service.list_history(db, run.id)


@router.post("/{run_id}/qa", response_model=RunQaMessageRead, status_code=status.HTTP_201_CREATED)
def ask_run_qa(
    run_id: int,
    payload: RunQaAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_run_or_404(db, run_id)
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="question is required")

    assistant_message = run_qa_service.answer_question(db, run, question, asked_by_user_id=current_user.id)
    db.commit()
    db.refresh(assistant_message)
    return assistant_message
