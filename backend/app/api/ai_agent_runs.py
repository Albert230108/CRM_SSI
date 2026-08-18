from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user, get_db
from app.models.ai_agent_run import AiAgentRun
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.ai_agent_run import AiAgentRunDetail, AiAgentRunRead

router = APIRouter(prefix="/ai-agent-runs", tags=["ai-agent-runs"])


def _with_tenant_name(db: Session, run: AiAgentRun) -> dict:
    """Runs are listed cross-tenant, so the tenant name is joined in for the UI."""
    name = db.query(Tenant.name).filter(Tenant.id == run.tenant_id).scalar()
    return {"tenant_name": name}


@router.get("", response_model=list[AiAgentRunRead])
def list_agent_runs(
    tenant_id: int | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> list[AiAgentRunRead]:
    query = db.query(AiAgentRun)
    if tenant_id is not None:
        query = query.filter(AiAgentRun.tenant_id == tenant_id)
    if status_filter:
        query = query.filter(AiAgentRun.status == status_filter)
    runs = query.order_by(AiAgentRun.created_at.desc(), AiAgentRun.id.desc()).limit(limit).all()
    return [
        AiAgentRunRead.model_validate(run).model_copy(update=_with_tenant_name(db, run)) for run in runs
    ]


@router.get("/{run_id}", response_model=AiAgentRunDetail)
def get_agent_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> AiAgentRunDetail:
    run = db.query(AiAgentRun).filter(AiAgentRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    return AiAgentRunDetail.model_validate(run).model_copy(update=_with_tenant_name(db, run))
