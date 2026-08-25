from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.action_tag_definition import ActionTagDefinition
from app.models.user import User
from app.services import action_tag_service

router = APIRouter(tags=["action-tags"])


class ActionTagDefinitionRead(BaseModel):
    id: int
    name: str
    color: str
    position: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ActionTagDefinitionCreate(BaseModel):
    name: str
    color: str


class ActionTagDefinitionUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None
    position: Optional[int] = None


@router.get("/action-tags", response_model=list[ActionTagDefinitionRead])
def list_action_tags(
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return action_tag_service.list_definitions(db, active_only=active_only)


@router.post("/action-tags", response_model=ActionTagDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_action_tag(
    payload: ActionTagDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.name.strip() or not payload.color.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name and color are required")
    existing = db.query(ActionTagDefinition).filter(ActionTagDefinition.name == payload.name.strip()).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A tag with this name already exists")
    definition = action_tag_service.add_definition(db, payload.name, payload.color)
    db.commit()
    db.refresh(definition)
    return definition


def _get_definition(db: Session, tag_id: int) -> ActionTagDefinition:
    definition = db.query(ActionTagDefinition).filter(ActionTagDefinition.id == tag_id).first()
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action tag not found")
    return definition


@router.patch("/action-tags/{tag_id}", response_model=ActionTagDefinitionRead)
def update_action_tag(
    tag_id: int,
    payload: ActionTagDefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    definition = _get_definition(db, tag_id)
    action_tag_service.update_definition(
        db,
        definition,
        name=payload.name,
        color=payload.color,
        is_active=payload.is_active,
        position=payload.position,
    )
    db.commit()
    db.refresh(definition)
    return definition


@router.delete("/action-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_action_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    definition = _get_definition(db, tag_id)
    action_tag_service.delete_definition(db, definition)
    db.commit()
