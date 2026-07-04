from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.communication import CommunicationCreate, CommunicationRead
from app.services.thread_timeline_service import MixedTimelineRead, build_tenant_thread_timeline
from app.services.whatsapp_client import send_whatsapp_message

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


@router.get("/tenants/{tenant_id}/grouped-thread", response_model=MixedTimelineRead)
def get_tenant_grouped_thread(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MixedTimelineRead:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    return build_tenant_thread_timeline(db, tenant_id)

@router.post("/tenants/{tenant_id}/send", response_model=CommunicationRead, status_code=status.HTTP_201_CREATED)
async def send_tenant_communication(
    tenant_id: int,
    payload: CommunicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Communication:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    channel = payload.channel.strip().lower()
    if channel not in {"email", "whatsapp"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported channel")

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

    if channel == "whatsapp":
        if not tenant.phone:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant phone is required for WhatsApp")
        await send_whatsapp_message(
            {
                "to": tenant.phone,
                "message": message,
            }
        )

    communication = Communication(
        tenant_id=tenant.id,
        channel=channel,
        direction="outbound",
        subject=payload.subject.strip() if payload.subject else None,
        message=message,
        created_at=datetime.now(timezone.utc),
    )
    db.add(communication)
    db.commit()
    db.refresh(communication)
    return communication



