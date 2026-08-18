from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BrainSectionCreate(BaseModel):
    title: str
    slug: str | None = None
    parent_id: int | None = None
    content: str | None = None
    is_active: bool = True


class BrainSectionUpdate(BaseModel):
    title: str
    slug: str | None = None
    content: str | None = None
    is_active: bool = True


class BrainSectionMove(BaseModel):
    parent_id: int | None = None
    position: int = 0


class BrainSectionRead(BaseModel):
    id: int
    parent_id: int | None = None
    path: str
    slug: str
    title: str
    content: str | None = None
    position: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BrainSectionNode(BrainSectionRead):
    children: list["BrainSectionNode"] = []


BrainSectionNode.model_rebuild()
