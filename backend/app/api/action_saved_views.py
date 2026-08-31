from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.action_saved_view import ActionSavedView
from app.models.user import User

router = APIRouter(tags=["action-saved-views"])

StatusValue = Literal["open", "done", "dismissed"]
Priority = Literal["p1", "p2", "p3", "p4"]
TagMatch = Literal["any", "all"]
DueBucket = Literal["overdue", "today", "upcoming"]
Scope = Literal["all", "tenant", "general"]
SortField = Literal["due_date", "priority", "created_at"]
SortDir = Literal["asc", "desc"]


class ActionSavedViewRead(BaseModel):
    id: int
    name: str
    position: int
    status: Optional[StatusValue] = None
    priority: Optional[Priority] = None
    tag_ids: list[int]
    tag_match: TagMatch
    due_bucket: Optional[DueBucket] = None
    scope: Scope
    sort_field: SortField
    sort_dir: SortDir
    created_at: datetime
    updated_at: datetime


class ActionSavedViewCreate(BaseModel):
    name: str
    status: Optional[StatusValue] = None
    priority: Optional[Priority] = None
    tag_ids: list[int] = []
    tag_match: TagMatch = "any"
    due_bucket: Optional[DueBucket] = None
    scope: Scope = "all"
    sort_field: SortField = "due_date"
    sort_dir: SortDir = "asc"
    position: Optional[int] = None


class ActionSavedViewUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[StatusValue] = None
    clear_status: bool = False
    priority: Optional[Priority] = None
    clear_priority: bool = False
    tag_ids: Optional[list[int]] = None
    tag_match: Optional[TagMatch] = None
    due_bucket: Optional[DueBucket] = None
    clear_due_bucket: bool = False
    scope: Optional[Scope] = None
    sort_field: Optional[SortField] = None
    sort_dir: Optional[SortDir] = None
    position: Optional[int] = None


def _to_read(view: ActionSavedView) -> ActionSavedViewRead:
    return ActionSavedViewRead(
        id=view.id,
        name=view.name,
        position=view.position,
        status=view.status,
        priority=view.priority,
        tag_ids=list(view.tag_ids or []),
        tag_match=view.tag_match,
        due_bucket=view.due_bucket,
        scope=view.scope,
        sort_field=view.sort_field,
        sort_dir=view.sort_dir,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _get_own_view(db: Session, view_id: int, user_id: int) -> ActionSavedView:
    view = (
        db.query(ActionSavedView)
        .filter(ActionSavedView.id == view_id, ActionSavedView.user_id == user_id)
        .first()
    )
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved view not found")
    return view


@router.get("/action-saved-views", response_model=list[ActionSavedViewRead])
def list_action_saved_views(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    views = (
        db.query(ActionSavedView)
        .filter(ActionSavedView.user_id == current_user.id)
        .order_by(ActionSavedView.position, ActionSavedView.id)
        .all()
    )
    return [_to_read(view) for view in views]


@router.post("/action-saved-views", response_model=ActionSavedViewRead, status_code=status.HTTP_201_CREATED)
def create_action_saved_view(
    payload: ActionSavedViewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")
    position = payload.position
    if position is None:
        position = db.query(ActionSavedView).filter(ActionSavedView.user_id == current_user.id).count()
    view = ActionSavedView(
        user_id=current_user.id,
        name=name,
        position=position,
        status=payload.status,
        priority=payload.priority,
        tag_ids=payload.tag_ids,
        tag_match=payload.tag_match,
        due_bucket=payload.due_bucket,
        scope=payload.scope,
        sort_field=payload.sort_field,
        sort_dir=payload.sort_dir,
    )
    db.add(view)
    db.commit()
    db.refresh(view)
    return _to_read(view)


@router.patch("/action-saved-views/{view_id}", response_model=ActionSavedViewRead)
def update_action_saved_view(
    view_id: int,
    payload: ActionSavedViewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    view = _get_own_view(db, view_id, current_user.id)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name cannot be empty")
        view.name = name
    if payload.clear_status:
        view.status = None
    elif payload.status is not None:
        view.status = payload.status
    if payload.clear_priority:
        view.priority = None
    elif payload.priority is not None:
        view.priority = payload.priority
    if payload.tag_ids is not None:
        view.tag_ids = payload.tag_ids
    if payload.tag_match is not None:
        view.tag_match = payload.tag_match
    if payload.clear_due_bucket:
        view.due_bucket = None
    elif payload.due_bucket is not None:
        view.due_bucket = payload.due_bucket
    if payload.scope is not None:
        view.scope = payload.scope
    if payload.sort_field is not None:
        view.sort_field = payload.sort_field
    if payload.sort_dir is not None:
        view.sort_dir = payload.sort_dir
    if payload.position is not None:
        view.position = payload.position
    db.commit()
    db.refresh(view)
    return _to_read(view)


@router.delete("/action-saved-views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_action_saved_view(
    view_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    view = _get_own_view(db, view_id, current_user.id)
    db.delete(view)
    db.commit()
