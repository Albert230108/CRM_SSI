from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.communication import CommunicationRead

router = APIRouter(prefix="/api/communications", tags=["communications"])


@router.get("/tenants/{tenant_id}/timeline", response_model=list[CommunicationRead])
def get_tenant_timeline(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Communication]:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    return (
        db.query(Communication)
        .filter(Communication.tenant_id == tenant_id)
        .order_by(Communication.created_at.asc(), Communication.id.asc())
        .all()
    )
