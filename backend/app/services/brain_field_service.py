"""The global structured working-memory schema (BrainFieldDefinition) and each tenant's values
for it (TenantBrainFieldValue).

Distinct from tenant_brain_service's free-text TenantBrainEntry list: a field definition
carries an admin-written ai_instruction telling the brain writer what to look for, and each
tenant gets at most one value row per field. See tenant_brain_service._build_prompt for how
both are combined into one LLM call.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.brain_field_definition import BrainFieldDefinition
from app.models.tenant_brain_field_value import TenantBrainFieldValue


def list_definitions(db: Session, *, active_only: bool = False) -> list[BrainFieldDefinition]:
    query = db.query(BrainFieldDefinition)
    if active_only:
        query = query.filter(BrainFieldDefinition.is_active.is_(True))
    return query.order_by(BrainFieldDefinition.position, BrainFieldDefinition.id).all()


def add_definition(db: Session, key: str, label: str, ai_instruction: str) -> BrainFieldDefinition:
    key = (key or "").strip()
    label = (label or "").strip()
    ai_instruction = (ai_instruction or "").strip()
    max_position = db.query(BrainFieldDefinition).count()
    definition = BrainFieldDefinition(
        key=key, label=label, ai_instruction=ai_instruction, position=max_position
    )
    db.add(definition)
    db.flush()
    return definition


def update_definition(
    db: Session,
    definition: BrainFieldDefinition,
    *,
    label: str | None = None,
    ai_instruction: str | None = None,
    is_active: bool | None = None,
    position: int | None = None,
) -> BrainFieldDefinition:
    if label is not None:
        definition.label = label.strip()
    if ai_instruction is not None:
        definition.ai_instruction = ai_instruction.strip()
    if is_active is not None:
        definition.is_active = is_active
    if position is not None:
        definition.position = position
    return definition


def delete_definition(db: Session, definition: BrainFieldDefinition) -> None:
    db.delete(definition)


def get_values_for_tenant(db: Session, tenant_id: int) -> dict[int, TenantBrainFieldValue]:
    rows = (
        db.query(TenantBrainFieldValue)
        .filter(TenantBrainFieldValue.tenant_id == tenant_id)
        .all()
    )
    return {row.field_definition_id: row for row in rows}


def set_value(
    db: Session,
    tenant_id: int,
    field_definition_id: int,
    value: str | None,
    *,
    source: str,
    updated_by_user_id: int | None = None,
) -> TenantBrainFieldValue:
    row = (
        db.query(TenantBrainFieldValue)
        .filter(
            TenantBrainFieldValue.tenant_id == tenant_id,
            TenantBrainFieldValue.field_definition_id == field_definition_id,
        )
        .first()
    )
    if row is None:
        row = TenantBrainFieldValue(tenant_id=tenant_id, field_definition_id=field_definition_id)
        db.add(row)
    row.value = value
    row.source = source
    row.updated_by_user_id = updated_by_user_id
    return row
