from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.brain_field_definition import BrainFieldDefinition
from app.models.tenant import Tenant
from app.models.user import User
from app.services import brain_field_service

router = APIRouter(tags=["brain-fields"])


class BrainFieldDefinitionRead(BaseModel):
    id: int
    key: str
    label: str
    ai_instruction: str
    position: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BrainFieldDefinitionCreate(BaseModel):
    key: str
    label: str
    ai_instruction: str


class BrainFieldDefinitionUpdate(BaseModel):
    label: Optional[str] = None
    ai_instruction: Optional[str] = None
    is_active: Optional[bool] = None
    position: Optional[int] = None


@router.get("/brain-fields", response_model=list[BrainFieldDefinitionRead])
def list_brain_fields(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return brain_field_service.list_definitions(db)


@router.post("/brain-fields", response_model=BrainFieldDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_brain_field(
    payload: BrainFieldDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.key.strip() or not payload.label.strip() or not payload.ai_instruction.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="key, label and ai_instruction are required")
    existing = db.query(BrainFieldDefinition).filter(BrainFieldDefinition.key == payload.key.strip()).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A field with this key already exists")
    definition = brain_field_service.add_definition(db, payload.key, payload.label, payload.ai_instruction)
    db.commit()
    db.refresh(definition)
    return definition


def _get_definition(db: Session, field_id: int) -> BrainFieldDefinition:
    definition = db.query(BrainFieldDefinition).filter(BrainFieldDefinition.id == field_id).first()
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brain field not found")
    return definition


@router.patch("/brain-fields/{field_id}", response_model=BrainFieldDefinitionRead)
def update_brain_field(
    field_id: int,
    payload: BrainFieldDefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    definition = _get_definition(db, field_id)
    brain_field_service.update_definition(
        db,
        definition,
        label=payload.label,
        ai_instruction=payload.ai_instruction,
        is_active=payload.is_active,
        position=payload.position,
    )
    db.commit()
    db.refresh(definition)
    return definition


@router.delete("/brain-fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brain_field(
    field_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    definition = _get_definition(db, field_id)
    brain_field_service.delete_definition(db, definition)
    db.commit()


class TenantBrainFieldValueRead(BaseModel):
    field_definition_id: int
    key: str
    label: str
    ai_instruction: str
    value: Optional[str] = None
    source: Optional[str] = None
    updated_at: Optional[datetime] = None


@router.get("/tenants/{tenant_id}/brain-fields", response_model=list[TenantBrainFieldValueRead])
def get_tenant_brain_fields(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    definitions = brain_field_service.list_definitions(db, active_only=True)
    values = brain_field_service.get_values_for_tenant(db, tenant_id)
    return [
        TenantBrainFieldValueRead(
            field_definition_id=definition.id,
            key=definition.key,
            label=definition.label,
            ai_instruction=definition.ai_instruction,
            value=(values[definition.id].value if definition.id in values else None),
            source=(values[definition.id].source if definition.id in values else None),
            updated_at=(values[definition.id].updated_at if definition.id in values else None),
        )
        for definition in definitions
    ]


class TenantBrainFieldValueUpdate(BaseModel):
    value: Optional[str] = None


@router.patch("/tenants/{tenant_id}/brain-fields/{field_id}", response_model=TenantBrainFieldValueRead)
def update_tenant_brain_field(
    tenant_id: int,
    field_id: int,
    payload: TenantBrainFieldValueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    definition = _get_definition(db, field_id)

    row = brain_field_service.set_value(
        db, tenant_id, field_id, payload.value, source="manual", updated_by_user_id=current_user.id
    )
    db.commit()
    db.refresh(row)
    return TenantBrainFieldValueRead(
        field_definition_id=definition.id,
        key=definition.key,
        label=definition.label,
        ai_instruction=definition.ai_instruction,
        value=row.value,
        source=row.source,
        updated_at=row.updated_at,
    )
