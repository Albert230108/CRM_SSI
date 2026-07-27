from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.notification import Notification, NotificationReadState
from app.models.user import User
from app.schemas.notification import NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


class UnreadCountRead(BaseModel):
    count: int


class MarkAllReadResult(BaseModel):
    marked: int


def _read_notification_ids(db: Session, user_id: int, notification_ids: list[int] | None = None) -> set[int]:
    query = db.query(NotificationReadState.notification_id).filter(NotificationReadState.user_id == user_id)
    if notification_ids is not None:
        query = query.filter(NotificationReadState.notification_id.in_(notification_ids))
    return {row[0] for row in query.all()}


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    unread_only: bool = False,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NotificationRead]:
    query = db.query(Notification).order_by(Notification.created_at.desc())
    if unread_only:
        read_subquery = db.query(NotificationReadState.notification_id).filter(
            NotificationReadState.user_id == current_user.id
        )
        query = query.filter(~Notification.id.in_(read_subquery))

    notifications = query.limit(limit).all()
    read_ids = _read_notification_ids(db, current_user.id, [n.id for n in notifications])

    return [
        NotificationRead(
            id=n.id,
            tenant_id=n.tenant_id,
            tenant_name=n.tenant_name,
            channel=n.channel,
            direction=n.direction,
            preview=n.preview,
            created_at=n.created_at,
            event_at=n.event_at,
            is_read=n.id in read_ids,
        )
        for n in notifications
    ]


@router.get("/unread-count", response_model=UnreadCountRead)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UnreadCountRead:
    total = db.query(func.count(Notification.id)).scalar() or 0
    read_count = (
        db.query(func.count(NotificationReadState.id))
        .filter(NotificationReadState.user_id == current_user.id)
        .scalar()
        or 0
    )
    return UnreadCountRead(count=max(total - read_count, 0))


@router.post("/{notification_id}/mark-read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationRead:
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    existing = (
        db.query(NotificationReadState)
        .filter(
            NotificationReadState.notification_id == notification_id,
            NotificationReadState.user_id == current_user.id,
        )
        .first()
    )
    if existing is None:
        db.add(NotificationReadState(notification_id=notification_id, user_id=current_user.id))
        db.commit()

    return NotificationRead(
        id=notification.id,
        tenant_id=notification.tenant_id,
        tenant_name=notification.tenant_name,
        channel=notification.channel,
        direction=notification.direction,
        preview=notification.preview,
        created_at=notification.created_at,
        event_at=notification.event_at,
        is_read=True,
    )


@router.post("/mark-all-read", response_model=MarkAllReadResult)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MarkAllReadResult:
    read_subquery = db.query(NotificationReadState.notification_id).filter(
        NotificationReadState.user_id == current_user.id
    )
    unread_ids = [
        row[0]
        for row in db.query(Notification.id).filter(~Notification.id.in_(read_subquery)).all()
    ]
    now = datetime.now(timezone.utc)
    for notification_id in unread_ids:
        db.add(NotificationReadState(notification_id=notification_id, user_id=current_user.id, read_at=now))
    db.commit()

    return MarkAllReadResult(marked=len(unread_ids))
