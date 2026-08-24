from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.action_item import ActionItem
from app.models.tenant import Tenant
from app.models.user import User
from app.services import action_item_service

router = APIRouter(tags=["action-items"])


class ActionItemRead(BaseModel):
    id: int
    tenant_id: int
    tenant_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    responsible_user_id: Optional[int] = None
    due_date: Optional[date] = None
    status: str
    source: str
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


def _to_read(item: ActionItem, tenant_name: Optional[str] = None) -> ActionItemRead:
    return ActionItemRead(
        id=item.id,
        tenant_id=item.tenant_id,
        tenant_name=tenant_name,
        title=item.title,
        description=item.description,
        responsible_user_id=item.responsible_user_id,
        due_date=item.due_date,
        status=item.status,
        source=item.source,
        created_by_user_id=item.created_by_user_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        completed_at=item.completed_at,
    )


@router.get("/action-items", response_model=list[ActionItemRead])
def list_action_items(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(ActionItem, Tenant.name)
        .outerjoin(Tenant, Tenant.id == ActionItem.tenant_id)
        .filter(ActionItem.status == status_filter if status_filter else True)
        .order_by(ActionItem.status == "done", ActionItem.due_date.is_(None), ActionItem.due_date, ActionItem.created_at.desc())
        .all()
    )
    return [_to_read(item, tenant_name) for item, tenant_name in rows]


@router.get("/tenants/{tenant_id}/action-items", response_model=list[ActionItemRead])
def list_tenant_action_items(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return [_to_read(item, tenant.name) for item in action_item_service.list_for_tenant(db, tenant_id)]


class ActionItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    responsible_user_id: Optional[int] = None
    due_date: Optional[date] = None


@router.post("/tenants/{tenant_id}/action-items", response_model=ActionItemRead, status_code=status.HTTP_201_CREATED)
def create_tenant_action_item(
    tenant_id: int,
    payload: ActionItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    item = action_item_service.create(
        db,
        tenant_id,
        payload.title,
        description=payload.description,
        responsible_user_id=payload.responsible_user_id,
        due_date=payload.due_date,
        source="manual",
        created_by_user_id=current_user.id,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required")
    db.commit()
    db.refresh(item)
    return _to_read(item, tenant.name)


def _get_item(db: Session, item_id: int) -> ActionItem:
    item = db.query(ActionItem).filter(ActionItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action item not found")
    return item


class ActionItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    responsible_user_id: Optional[int] = None
    due_date: Optional[date] = None


@router.patch("/action-items/{item_id}", response_model=ActionItemRead)
def update_action_item(
    item_id: int,
    payload: ActionItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = _get_item(db, item_id)
    action_item_service.update(
        db,
        item,
        title=payload.title,
        description=payload.description,
        responsible_user_id=payload.responsible_user_id,
        due_date=payload.due_date,
    )
    db.commit()
    db.refresh(item)
    tenant_name = db.query(Tenant.name).filter(Tenant.id == item.tenant_id).scalar()
    return _to_read(item, tenant_name)


@router.post("/action-items/{item_id}/complete", response_model=ActionItemRead)
def complete_action_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_item(db, item_id)
    action_item_service.complete(db, item)
    db.commit()
    db.refresh(item)
    tenant_name = db.query(Tenant.name).filter(Tenant.id == item.tenant_id).scalar()
    return _to_read(item, tenant_name)


@router.post("/action-items/{item_id}/dismiss", response_model=ActionItemRead)
def dismiss_action_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_item(db, item_id)
    action_item_service.dismiss(db, item)
    db.commit()
    db.refresh(item)
    tenant_name = db.query(Tenant.name).filter(Tenant.id == item.tenant_id).scalar()
    return _to_read(item, tenant_name)


@router.post("/action-items/{item_id}/reopen", response_model=ActionItemRead)
def reopen_action_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_item(db, item_id)
    action_item_service.reopen(db, item)
    db.commit()
    db.refresh(item)
    tenant_name = db.query(Tenant.name).filter(Tenant.id == item.tenant_id).scalar()
    return _to_read(item, tenant_name)
