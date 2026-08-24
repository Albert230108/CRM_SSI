from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.working_memory_rule import (
    SOURCE_AI_SUGGESTED,
    SOURCE_MANUAL,
    STATUS_ACTIVE,
    STATUS_DISMISSED,
    STATUS_PENDING_APPROVAL,
    WorkingMemoryRule,
)


def list_all(db: Session) -> list[WorkingMemoryRule]:
    return db.query(WorkingMemoryRule).order_by(WorkingMemoryRule.created_at.desc()).all()


def list_active(db: Session) -> list[WorkingMemoryRule]:
    return (
        db.query(WorkingMemoryRule)
        .filter(WorkingMemoryRule.status == STATUS_ACTIVE)
        .order_by(WorkingMemoryRule.created_at.desc())
        .all()
    )


def add_rule(
    db: Session,
    condition_text: str,
    action_text: str,
    *,
    source: str = SOURCE_MANUAL,
    status: str = STATUS_ACTIVE,
    created_by_user_id: int | None = None,
) -> WorkingMemoryRule | None:
    condition_text = (condition_text or "").strip()
    action_text = (action_text or "").strip()
    if not condition_text or not action_text:
        return None
    rule = WorkingMemoryRule(
        condition_text=condition_text,
        action_text=action_text,
        status=status,
        source=source,
        created_by_user_id=created_by_user_id,
    )
    db.add(rule)
    db.flush()
    return rule


def update_rule(
    db: Session,
    rule: WorkingMemoryRule,
    *,
    condition_text: str | None = None,
    action_text: str | None = None,
) -> WorkingMemoryRule:
    if condition_text is not None:
        rule.condition_text = condition_text.strip()
    if action_text is not None:
        rule.action_text = action_text.strip()
    return rule


def approve_rule(db: Session, rule: WorkingMemoryRule) -> WorkingMemoryRule:
    rule.status = STATUS_ACTIVE
    return rule


def dismiss_rule(db: Session, rule: WorkingMemoryRule) -> WorkingMemoryRule:
    rule.status = STATUS_DISMISSED
    return rule


def delete_rule(db: Session, rule: WorkingMemoryRule) -> None:
    db.delete(rule)
