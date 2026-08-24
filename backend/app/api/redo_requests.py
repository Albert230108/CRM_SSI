from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.models.user import User
from app.services import memory_redo_service, memory_suggestion_service, redo_request_log_service

router = APIRouter(prefix="/redo-requests", tags=["redo-requests"])


class RedoRequestRead(BaseModel):
    id: int
    ai_auto_draft_id: int | None = None
    tenant_id: int
    tenant_name: Optional[str] = None
    channel: str
    what: str
    why: Optional[str] = None
    requested_by_user_id: Optional[int] = None
    requested_by_email: Optional[str] = None
    ai_agent_run_id: int | None = None
    memory_redo_run_id: int | None = None
    processed_at: datetime | None = None
    created_at: datetime


class ReplayRedoRequestsResult(BaseModel):
    processed: int
    remaining: int


@router.get("", response_model=list[RedoRequestRead])
def list_redo_requests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(RedoRequestLog, Tenant.name, User.email)
        .outerjoin(Tenant, Tenant.id == RedoRequestLog.tenant_id)
        .outerjoin(User, User.id == RedoRequestLog.requested_by_user_id)
        .order_by(RedoRequestLog.created_at.desc())
        .all()
    )
    return [
        RedoRequestRead(
            id=log.id,
            ai_auto_draft_id=log.ai_auto_draft_id,
            tenant_id=log.tenant_id,
            tenant_name=tenant_name,
            channel=log.channel,
            what=log.what,
            why=log.why,
            requested_by_user_id=log.requested_by_user_id,
            requested_by_email=requester_email,
            ai_agent_run_id=log.ai_agent_run_id,
            memory_redo_run_id=log.memory_redo_run_id,
            processed_at=log.processed_at,
            created_at=log.created_at,
        )
        for log, tenant_name, requester_email in rows
    ]


@router.post("/replay-pending", response_model=ReplayRedoRequestsResult)
def replay_pending_redo_requests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ReplayRedoRequestsResult:
    pending = redo_request_log_service.list_unprocessed(db, limit=100)
    processed = 0
    for redo_log in pending:
        try:
            memory_redo_service.process_redo_request_log(db, redo_log.id)
            if redo_log.processed_at is not None:
                db.commit()
                processed += 1
            else:
                db.rollback()
        except Exception:
            db.rollback()
    remaining = db.query(RedoRequestLog).filter(RedoRequestLog.processed_at.is_(None)).count()
    return ReplayRedoRequestsResult(processed=processed, remaining=remaining)
