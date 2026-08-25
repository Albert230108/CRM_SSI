from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_agent_profile import AiAgentProfile
from app.models.ai_reply_template import AiReplyTemplate
from app.models.memory_suggestion import (
    KIND_ACTION_ITEM_COMPLETE,
    KIND_ACTION_ITEM_DELETE,
    KIND_ACTION_ITEM_MODIFY,
    KIND_PROFILE_CHANGE,
    KIND_TEMPLATE_CHANGE,
    STATUS_PENDING,
    MemorySuggestion,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services import memory_suggestion_service

router = APIRouter(prefix="/memory-suggestions", tags=["memory-suggestions"])


class MemorySuggestionRead(BaseModel):
    id: int
    kind: str
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    target_id: Optional[int] = None
    # Human-readable name of the target profile/template for profile_change/template_change
    # suggestions, since proposed_value only carries the raw id.
    target_name: Optional[str] = None
    proposed_value: dict[str, Any]
    reasoning: Optional[str] = None
    status: str
    created_at: datetime


def _to_read(suggestion: MemorySuggestion, tenant_name: Optional[str], target_name: Optional[str]) -> MemorySuggestionRead:
    return MemorySuggestionRead(
        id=suggestion.id,
        kind=suggestion.kind,
        tenant_id=suggestion.tenant_id,
        tenant_name=tenant_name,
        target_id=suggestion.target_id,
        target_name=target_name,
        proposed_value=suggestion.proposed_value,
        reasoning=suggestion.reasoning,
        status=suggestion.status,
        created_at=suggestion.created_at,
    )


@router.get("", response_model=list[MemorySuggestionRead])
def list_memory_suggestions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Action-item modify/delete/complete suggestions have their own dedicated review surface on the
    # Actions page (GET /api/action-items/pending-suggestions) - excluded here so they're not
    # reviewed twice in two different places.
    rows = memory_suggestion_service.list_pending(db, exclude_kinds={KIND_ACTION_ITEM_MODIFY, KIND_ACTION_ITEM_DELETE, KIND_ACTION_ITEM_COMPLETE})
    tenant_names = {
        t.id: t.name for t in db.query(Tenant).filter(Tenant.id.in_([r.tenant_id for r in rows if r.tenant_id is not None])).all()
    }
    profile_ids = [r.target_id for r in rows if r.kind == KIND_PROFILE_CHANGE and r.target_id is not None]
    template_ids = [r.target_id for r in rows if r.kind == KIND_TEMPLATE_CHANGE and r.target_id is not None]
    profile_names = {p.id: f"{p.name} ({p.role})" for p in db.query(AiAgentProfile).filter(AiAgentProfile.id.in_(profile_ids)).all()}
    template_names = {t.id: t.name for t in db.query(AiReplyTemplate).filter(AiReplyTemplate.id.in_(template_ids)).all()}

    def _target_name(row: MemorySuggestion) -> Optional[str]:
        if row.kind == KIND_PROFILE_CHANGE:
            return profile_names.get(row.target_id)
        if row.kind == KIND_TEMPLATE_CHANGE:
            return template_names.get(row.target_id)
        return None

    return [_to_read(row, tenant_names.get(row.tenant_id), _target_name(row)) for row in rows]


def _get_suggestion(db: Session, suggestion_id: int) -> MemorySuggestion:
    suggestion = db.query(MemorySuggestion).filter(MemorySuggestion.id == suggestion_id).first()
    if suggestion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
    return suggestion


class MemorySuggestionActionResult(BaseModel):
    applied: bool
    message: str


@router.post("/{suggestion_id}/approve", response_model=MemorySuggestionActionResult)
def approve_memory_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    suggestion = _get_suggestion(db, suggestion_id)
    if suggestion.status != STATUS_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This suggestion has already been reviewed")
    result = memory_suggestion_service.approve(db, suggestion, reviewer_id=current_user.id)
    db.commit()
    return MemorySuggestionActionResult(applied=result.applied, message=result.message)


@router.post("/{suggestion_id}/reject", response_model=MemorySuggestionActionResult)
def reject_memory_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    suggestion = _get_suggestion(db, suggestion_id)
    if suggestion.status != STATUS_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This suggestion has already been reviewed")
    memory_suggestion_service.reject(db, suggestion, reviewer_id=current_user.id)
    db.commit()
    return MemorySuggestionActionResult(applied=False, message="Suggestion rejected.")
