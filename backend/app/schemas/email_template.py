from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EmailTemplateCreate(BaseModel):
    name: str
    subject: str | None = None
    body: str


class EmailTemplateUpdate(BaseModel):
    name: str
    subject: str | None = None
    body: str


class EmailTemplateRead(BaseModel):
    id: int
    name: str
    subject: str | None = None
    body: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EmailTemplatePreviewRequest(BaseModel):
    tenant_id: int


class EmailTemplatePreviewResponse(BaseModel):
    subject: str | None = None
    body: str
