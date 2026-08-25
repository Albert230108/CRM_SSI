from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.action_item import ActionItem
from app.models.action_tag_definition import ActionTagDefinition
from app.models.memory_suggestion import KIND_ACTION_ITEM_DELETE
from app.models.tenant import Tenant
from app.models.user import User
from app.services import action_item_parse_service, action_item_service, memory_suggestion_service

router = APIRouter(tags=["action-items"])

Priority = Literal["p1", "p2", "p3", "p4"]
RecurrenceAnchor = Literal["due_date", "completed_at"]


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
    tag_id: Optional[int] = None
    tag_name: Optional[str] = None
    tag_color: Optional[str] = None
    priority: Optional[Priority] = None
    recurrence_interval_days: Optional[int] = None
    recurrence_anchor: Optional[RecurrenceAnchor] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


def _to_read(item: ActionItem, tenant_name: Optional[str] = None, tag: Optional[ActionTagDefinition] = None) -> ActionItemRead:
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
        tag_id=item.tag_id,
        tag_name=tag.name if tag is not None else None,
        tag_color=tag.color if tag is not None else None,
        priority=item.priority,
        recurrence_interval_days=item.recurrence_interval_days,
        recurrence_anchor=item.recurrence_anchor,
        created_by_user_id=item.created_by_user_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        completed_at=item.completed_at,
    )


def _tags_by_id(db: Session, items: list[ActionItem]) -> dict[int, ActionTagDefinition]:
    tag_ids = {item.tag_id for item in items if item.tag_id is not None}
    if not tag_ids:
        return {}
    return {tag.id: tag for tag in db.query(ActionTagDefinition).filter(ActionTagDefinition.id.in_(tag_ids)).all()}


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
    tags = _tags_by_id(db, [item for item, _ in rows])
    return [_to_read(item, tenant_name, tags.get(item.tag_id)) for item, tenant_name in rows]


@router.get("/tenants/{tenant_id}/action-items", response_model=list[ActionItemRead])
def list_tenant_action_items(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    items = action_item_service.list_for_tenant(db, tenant_id)
    tags = _tags_by_id(db, items)
    return [_to_read(item, tenant.name, tags.get(item.tag_id)) for item in items]


class ActionItemSuggestionSnapshot(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[Priority] = None
    tag_name: Optional[str] = None
    tag_color: Optional[str] = None
    status: str


class ActionItemSuggestionRead(BaseModel):
    id: int
    kind: str  # action_item_modify | action_item_delete
    tenant_id: int
    tenant_name: Optional[str] = None
    action_item_id: int
    current: ActionItemSuggestionSnapshot
    proposed: dict
    reasoning: Optional[str] = None
    created_at: datetime


@router.get("/action-items/pending-suggestions", response_model=list[ActionItemSuggestionRead])
def list_action_item_pending_suggestions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI-proposed modifications/deletions of *existing* action items, awaiting human review -
    distinct from the generic working-memory Pending Suggestions tab (see memory_suggestion_service
    for why these kinds are excluded there). New item creation needs no review - see
    action_writer_service.py.
    """
    suggestions = memory_suggestion_service.list_pending_action_item_suggestions(db)
    if not suggestions:
        return []

    item_ids = {s.target_id for s in suggestions if s.target_id is not None}
    items = {item.id: item for item in db.query(ActionItem).filter(ActionItem.id.in_(item_ids)).all()}
    tenant_ids = {item.tenant_id for item in items.values()}
    tenant_names = {t.id: t.name for t in db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).all()}

    tag_ids = {item.tag_id for item in items.values() if item.tag_id is not None}
    for s in suggestions:
        proposed_tag_id = (s.proposed_value or {}).get("tag_id")
        if isinstance(proposed_tag_id, int):
            tag_ids.add(proposed_tag_id)
    tags = {tag.id: tag for tag in db.query(ActionTagDefinition).filter(ActionTagDefinition.id.in_(tag_ids)).all()}

    results: list[ActionItemSuggestionRead] = []
    for s in suggestions:
        item = items.get(s.target_id)
        if item is None:
            continue
        current_tag = tags.get(item.tag_id) if item.tag_id is not None else None
        proposed = dict(s.proposed_value or {})
        if s.kind == KIND_ACTION_ITEM_DELETE:
            proposed = {"deleted": True}
        elif "tag_id" in proposed:
            proposed_tag = tags.get(proposed["tag_id"])
            proposed["tag_name"] = proposed_tag.name if proposed_tag else None
        results.append(
            ActionItemSuggestionRead(
                id=s.id,
                kind=s.kind,
                tenant_id=item.tenant_id,
                tenant_name=tenant_names.get(item.tenant_id),
                action_item_id=item.id,
                current=ActionItemSuggestionSnapshot(
                    title=item.title,
                    description=item.description,
                    due_date=item.due_date,
                    priority=item.priority,
                    tag_name=current_tag.name if current_tag else None,
                    tag_color=current_tag.color if current_tag else None,
                    status=item.status,
                ),
                proposed=proposed,
                reasoning=s.reasoning,
                created_at=s.created_at,
            )
        )
    return results


class ActionItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    responsible_user_id: Optional[int] = None
    due_date: Optional[date] = None
    tag_id: Optional[int] = None
    priority: Optional[Priority] = None
    recurrence_interval_days: Optional[int] = None
    recurrence_anchor: RecurrenceAnchor = "due_date"


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
        tag_id=payload.tag_id,
        priority=payload.priority,
        recurrence_interval_days=payload.recurrence_interval_days,
        recurrence_anchor=payload.recurrence_anchor if payload.recurrence_interval_days else None,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required")
    db.commit()
    db.refresh(item)
    tag = db.query(ActionTagDefinition).filter(ActionTagDefinition.id == item.tag_id).first() if item.tag_id else None
    return _to_read(item, tenant.name, tag)


class ActionItemParseRequest(BaseModel):
    text: str


class ActionItemParseResult(BaseModel):
    title: str
    due_date: Optional[date] = None
    priority: Optional[Priority] = None


@router.post("/tenants/{tenant_id}/action-items/parse", response_model=ActionItemParseResult)
def parse_action_item_text(
    tenant_id: int,
    payload: ActionItemParseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
    parsed = action_item_parse_service.parse_quick_add(text)
    if parsed is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not parse that into a task")
    return ActionItemParseResult(**parsed)


def _get_item(db: Session, item_id: int) -> ActionItem:
    item = db.query(ActionItem).filter(ActionItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action item not found")
    return item


def _read_with_lookups(db: Session, item: ActionItem) -> ActionItemRead:
    tenant_name = db.query(Tenant.name).filter(Tenant.id == item.tenant_id).scalar()
    tag = db.query(ActionTagDefinition).filter(ActionTagDefinition.id == item.tag_id).first() if item.tag_id else None
    return _to_read(item, tenant_name, tag)


class ActionItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    responsible_user_id: Optional[int] = None
    due_date: Optional[date] = None
    tag_id: Optional[int] = None
    clear_tag: bool = False
    priority: Optional[Priority] = None
    clear_priority: bool = False
    recurrence_interval_days: Optional[int] = None
    clear_recurrence: bool = False
    recurrence_anchor: Optional[RecurrenceAnchor] = None


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
        tag_id=payload.tag_id,
        clear_tag=payload.clear_tag,
        priority=payload.priority,
        clear_priority=payload.clear_priority,
        recurrence_interval_days=payload.recurrence_interval_days,
        clear_recurrence=payload.clear_recurrence,
        recurrence_anchor=payload.recurrence_anchor,
    )
    db.commit()
    db.refresh(item)
    return _read_with_lookups(db, item)


@router.post("/action-items/{item_id}/complete", response_model=ActionItemRead)
def complete_action_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_item(db, item_id)
    action_item_service.complete(db, item)
    db.commit()
    db.refresh(item)
    return _read_with_lookups(db, item)


@router.post("/action-items/{item_id}/dismiss", response_model=ActionItemRead)
def dismiss_action_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_item(db, item_id)
    action_item_service.dismiss(db, item)
    db.commit()
    db.refresh(item)
    return _read_with_lookups(db, item)


@router.post("/action-items/{item_id}/reopen", response_model=ActionItemRead)
def reopen_action_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_item(db, item_id)
    action_item_service.reopen(db, item)
    db.commit()
    db.refresh(item)
    return _read_with_lookups(db, item)
