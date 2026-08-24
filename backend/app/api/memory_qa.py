from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.memory_qa_message import MemoryQaMessage
from app.models.tenant import Tenant
from app.models.user import User
from app.services import memory_qa_service

router = APIRouter(tags=["memory-qa"])


class MemoryQaMessageRead(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


@router.get("/tenants/{tenant_id}/memory-qa", response_model=list[MemoryQaMessageRead])
def get_memory_qa_history(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return memory_qa_service.list_history(db, tenant_id)


class MemoryQaAskRequest(BaseModel):
    question: str


@router.post("/tenants/{tenant_id}/memory-qa", response_model=MemoryQaMessageRead, status_code=status.HTTP_201_CREATED)
def ask_memory_qa(
    tenant_id: int,
    payload: MemoryQaAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="question is required")

    assistant_message = memory_qa_service.answer_question(db, tenant, question, asked_by_user_id=current_user.id)
    db.commit()
    db.refresh(assistant_message)
    return assistant_message
