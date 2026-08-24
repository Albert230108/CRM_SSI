from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.action_item import SOURCE_AI, STATUS_DISMISSED, STATUS_DONE, STATUS_OPEN, ActionItem


def list_for_tenant(db: Session, tenant_id: int) -> list[ActionItem]:
    return (
        db.query(ActionItem)
        .filter(ActionItem.tenant_id == tenant_id)
        .order_by(ActionItem.status == STATUS_DONE, ActionItem.due_date.is_(None), ActionItem.due_date, ActionItem.created_at.desc())
        .all()
    )


def list_all(db: Session, *, status_filter: str | None = None) -> list[ActionItem]:
    query = db.query(ActionItem)
    if status_filter:
        query = query.filter(ActionItem.status == status_filter)
    return query.order_by(ActionItem.status == STATUS_DONE, ActionItem.due_date.is_(None), ActionItem.due_date, ActionItem.created_at.desc()).all()


def create(
    db: Session,
    tenant_id: int,
    title: str,
    *,
    description: str | None = None,
    responsible_user_id: int | None = None,
    due_date: date | None = None,
    source: str = "manual",
    created_by_user_id: int | None = None,
) -> ActionItem | None:
    title = (title or "").strip()
    if not title:
        return None
    item = ActionItem(
        tenant_id=tenant_id,
        title=title,
        description=(description or "").strip() or None,
        responsible_user_id=responsible_user_id,
        due_date=due_date,
        status=STATUS_OPEN,
        source=source,
        created_by_user_id=created_by_user_id,
    )
    db.add(item)
    db.flush()
    return item


def create_ai_item(db: Session, tenant_id: int, title: str, description: str | None, due_date: date | None) -> ActionItem | None:
    return create(db, tenant_id, title, description=description, due_date=due_date, source=SOURCE_AI)


def update(
    db: Session,
    item: ActionItem,
    *,
    title: str | None = None,
    description: str | None = None,
    responsible_user_id: int | None = None,
    due_date: date | None = None,
) -> ActionItem:
    if title is not None:
        item.title = title.strip()
    if description is not None:
        item.description = description.strip() or None
    if responsible_user_id is not None:
        item.responsible_user_id = responsible_user_id
    if due_date is not None:
        item.due_date = due_date
    return item


def complete(db: Session, item: ActionItem) -> ActionItem:
    item.status = STATUS_DONE
    item.completed_at = datetime.now(timezone.utc)
    return item


def dismiss(db: Session, item: ActionItem) -> ActionItem:
    item.status = STATUS_DISMISSED
    return item


def reopen(db: Session, item: ActionItem) -> ActionItem:
    item.status = STATUS_OPEN
    item.completed_at = None
    return item
