"""The global action-tag palette (ActionTagDefinition). Mirrors brain_field_service's shape for
the same reasons - admin-authored, position-ordered, is_active-flagged."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.action_tag_definition import ActionTagDefinition


def list_definitions(db: Session, *, active_only: bool = False) -> list[ActionTagDefinition]:
    query = db.query(ActionTagDefinition)
    if active_only:
        query = query.filter(ActionTagDefinition.is_active.is_(True))
    return query.order_by(ActionTagDefinition.position, ActionTagDefinition.id).all()


def add_definition(db: Session, name: str, color: str) -> ActionTagDefinition:
    name = (name or "").strip()
    color = (color or "").strip()
    max_position = db.query(ActionTagDefinition).count()
    definition = ActionTagDefinition(name=name, color=color, position=max_position)
    db.add(definition)
    db.flush()
    return definition


def update_definition(
    db: Session,
    definition: ActionTagDefinition,
    *,
    name: str | None = None,
    color: str | None = None,
    is_active: bool | None = None,
    position: int | None = None,
) -> ActionTagDefinition:
    if name is not None:
        definition.name = name.strip()
    if color is not None:
        definition.color = color.strip()
    if is_active is not None:
        definition.is_active = is_active
    if position is not None:
        definition.position = position
    return definition


def delete_definition(db: Session, definition: ActionTagDefinition) -> None:
    db.delete(definition)
