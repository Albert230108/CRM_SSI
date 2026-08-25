from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.action_item import SOURCE_AI, STATUS_DISMISSED, STATUS_DONE, STATUS_OPEN, ActionItem
from app.models.action_item_tag import ActionItemTag
from app.models.action_tag_definition import ActionTagDefinition


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


def _sync_tags(db: Session, item: ActionItem, tag_ids: list[int] | None) -> None:
    if tag_ids is None:
        return
    unique_ids = list(dict.fromkeys(tag_ids))
    if unique_ids:
        found = {row[0] for row in db.query(ActionTagDefinition.id).filter(ActionTagDefinition.id.in_(unique_ids)).all()}
        missing = [tag_id for tag_id in unique_ids if tag_id not in found]
        if missing:
            raise ValueError(f"Unknown action tag id(s): {', '.join(str(value) for value in missing)}")
    existing_links = {link.tag_id: link for link in item.tag_links}
    new_links = []
    for index, tag_id in enumerate(unique_ids):
        link = existing_links.get(tag_id)
        if link is not None:
            link.position = index
            new_links.append(link)
        else:
            new_links.append(ActionItemTag(tag_id=tag_id, position=index))
    item.tag_links = new_links


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
    tag_ids: list[int] | None = None,
    priority: str | None = None,
    recurrence_interval_days: int | None = None,
    recurrence_anchor: str | None = None,
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
        priority=priority,
        recurrence_interval_days=recurrence_interval_days,
        recurrence_anchor=recurrence_anchor,
    )
    db.add(item)
    db.flush()
    _sync_tags(db, item, tag_ids)
    return item


def create_ai_item(
    db: Session,
    tenant_id: int,
    title: str,
    description: str | None,
    due_date: date | None,
    *,
    tag_ids: list[int] | None = None,
    priority: str | None = None,
) -> ActionItem | None:
    return create(db, tenant_id, title, description=description, due_date=due_date, source=SOURCE_AI, tag_ids=tag_ids, priority=priority)


def update(
    db: Session,
    item: ActionItem,
    *,
    title: str | None = None,
    description: str | None = None,
    responsible_user_id: int | None = None,
    due_date: date | None = None,
    tag_ids: list[int] | None = None,
    priority: str | None = None,
    clear_priority: bool = False,
    recurrence_interval_days: int | None = None,
    clear_recurrence: bool = False,
    recurrence_anchor: str | None = None,
) -> ActionItem:
    if title is not None:
        item.title = title.strip()
    if description is not None:
        item.description = description.strip() or None
    if responsible_user_id is not None:
        item.responsible_user_id = responsible_user_id
    if due_date is not None:
        item.due_date = due_date
    _sync_tags(db, item, tag_ids)
    if clear_priority:
        item.priority = None
    elif priority is not None:
        item.priority = priority
    if clear_recurrence:
        item.recurrence_interval_days = None
        item.recurrence_anchor = None
    elif recurrence_interval_days is not None:
        item.recurrence_interval_days = recurrence_interval_days
        if recurrence_anchor is not None:
            item.recurrence_anchor = recurrence_anchor
    return item


def complete(db: Session, item: ActionItem) -> ActionItem:
    item.status = STATUS_DONE
    item.completed_at = datetime.now(timezone.utc)
    if item.recurrence_interval_days:
        anchor_date = date.today() if item.recurrence_anchor == "completed_at" else (item.due_date or date.today())
        next_due = anchor_date + timedelta(days=item.recurrence_interval_days)
        create(
            db,
            item.tenant_id,
            item.title,
            description=item.description,
            responsible_user_id=item.responsible_user_id,
            due_date=next_due,
            source=item.source,
            tag_ids=item.tag_ids,
            priority=item.priority,
            recurrence_interval_days=item.recurrence_interval_days,
            recurrence_anchor=item.recurrence_anchor,
        )
    return item


def dismiss(db: Session, item: ActionItem) -> ActionItem:
    item.status = STATUS_DISMISSED
    return item


def reopen(db: Session, item: ActionItem) -> ActionItem:
    item.status = STATUS_OPEN
    item.completed_at = None
    return item
