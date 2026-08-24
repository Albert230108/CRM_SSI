from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.working_memory_rule import STATUS_PENDING_APPROVAL, WorkingMemoryRule
from app.services import working_memory_rule_service

router = APIRouter(prefix="/working-memory-rules", tags=["working-memory-rules"])


class WorkingMemoryRuleRead(BaseModel):
    id: int
    condition_text: str
    action_text: str
    status: str
    source: str
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[WorkingMemoryRuleRead])
def list_rules(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return working_memory_rule_service.list_all(db)


class WorkingMemoryRuleCreate(BaseModel):
    condition_text: str
    action_text: str


@router.post("", response_model=WorkingMemoryRuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: WorkingMemoryRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = working_memory_rule_service.add_rule(
        db, payload.condition_text, payload.action_text, created_by_user_id=current_user.id
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="condition_text and action_text are required")
    db.commit()
    db.refresh(rule)
    return rule


def _get_rule(db: Session, rule_id: int) -> WorkingMemoryRule:
    rule = db.query(WorkingMemoryRule).filter(WorkingMemoryRule.id == rule_id).first()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


class WorkingMemoryRuleUpdate(BaseModel):
    condition_text: Optional[str] = None
    action_text: Optional[str] = None


@router.patch("/{rule_id}", response_model=WorkingMemoryRuleRead)
def update_rule(
    rule_id: int,
    payload: WorkingMemoryRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = _get_rule(db, rule_id)
    working_memory_rule_service.update_rule(db, rule, condition_text=payload.condition_text, action_text=payload.action_text)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> None:
    rule = _get_rule(db, rule_id)
    working_memory_rule_service.delete_rule(db, rule)
    db.commit()


@router.post("/{rule_id}/approve", response_model=WorkingMemoryRuleRead)
def approve_rule(rule_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rule = _get_rule(db, rule_id)
    if rule.status != STATUS_PENDING_APPROVAL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rule is not pending approval")
    working_memory_rule_service.approve_rule(db, rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/{rule_id}/reject", response_model=WorkingMemoryRuleRead)
def reject_rule(rule_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rule = _get_rule(db, rule_id)
    if rule.status != STATUS_PENDING_APPROVAL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rule is not pending approval")
    working_memory_rule_service.dismiss_rule(db, rule)
    db.commit()
    db.refresh(rule)
    return rule
