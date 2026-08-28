from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.models.user import User
from app.services import memory_redo_service, memory_suggestion_service, redo_qa_service, redo_request_log_service

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
    reviewed: bool = False
    processed_at: datetime | None = None
    created_at: datetime


class ReplayRedoRequestsResult(BaseModel):
    processed: int
    remaining: int


class RedoRequestUpdate(BaseModel):
    reviewed: bool


class RedoQaMessageRead(BaseModel):
    id: int
    ai_agent_run_id: int | None = None
    role: str
    content: str
    created_at: datetime


class RedoQaContextRead(BaseModel):
    what: str
    why: Optional[str] = None
    instructions: str
    qa_preamble: str
    model: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    run_log_text: str


class RedoQaAskRequest(BaseModel):
    question: str


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
            reviewed=log.reviewed,
            processed_at=log.processed_at,
            created_at=log.created_at,
        )
        for log, tenant_name, requester_email in rows
    ]


@router.patch("/{redo_request_id}", response_model=RedoRequestRead)
def update_redo_request(
    redo_request_id: int,
    payload: RedoRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RedoRequestRead:
    redo_log = db.query(RedoRequestLog).filter(RedoRequestLog.id == redo_request_id).first()
    if redo_log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Redo request not found")
    redo_log.reviewed = payload.reviewed
    db.commit()
    db.refresh(redo_log)
    tenant_name = db.query(Tenant.name).filter(Tenant.id == redo_log.tenant_id).scalar()
    requester_email = db.query(User.email).filter(User.id == redo_log.requested_by_user_id).scalar()
    return RedoRequestRead(
        id=redo_log.id,
        ai_auto_draft_id=redo_log.ai_auto_draft_id,
        tenant_id=redo_log.tenant_id,
        tenant_name=tenant_name,
        channel=redo_log.channel,
        what=redo_log.what,
        why=redo_log.why,
        requested_by_user_id=redo_log.requested_by_user_id,
        requested_by_email=requester_email,
        ai_agent_run_id=redo_log.ai_agent_run_id,
        memory_redo_run_id=redo_log.memory_redo_run_id,
        reviewed=redo_log.reviewed,
        processed_at=redo_log.processed_at,
        created_at=redo_log.created_at,
    )


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


@router.get("/{redo_request_id}/qa/context", response_model=RedoQaContextRead)
def get_redo_qa_context(
    redo_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    redo_log = db.query(RedoRequestLog).filter(RedoRequestLog.id == redo_request_id).first()
    if redo_log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Redo request not found")
    return redo_qa_service.get_context(db, redo_log)


@router.get("/{redo_request_id}/qa", response_model=list[RedoQaMessageRead])
def list_redo_qa_history(
    redo_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    redo_log = db.query(RedoRequestLog).filter(RedoRequestLog.id == redo_request_id).first()
    if redo_log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Redo request not found")
    return redo_qa_service.list_history(db, redo_log.id)


@router.post("/{redo_request_id}/qa", response_model=RedoQaMessageRead, status_code=status.HTTP_201_CREATED)
def ask_redo_qa(
    redo_request_id: int,
    payload: RedoQaAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    redo_log = db.query(RedoRequestLog).filter(RedoRequestLog.id == redo_request_id).first()
    if redo_log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Redo request not found")
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="question is required")

    assistant_message = redo_qa_service.answer_question(db, redo_log, question, asked_by_user_id=current_user.id)
    db.commit()
    db.refresh(assistant_message)
    return assistant_message
