from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter(prefix="/redo-requests", tags=["redo-requests"])


class RedoRequestRead(BaseModel):
    id: int
    ai_auto_draft_id: int
    tenant_id: int
    tenant_name: Optional[str] = None
    channel: str
    what: str
    why: Optional[str] = None
    requested_by_user_id: Optional[int] = None
    requested_by_email: Optional[str] = None
    created_at: datetime


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
            created_at=log.created_at,
        )
        for log, tenant_name, requester_email in rows
    ]
