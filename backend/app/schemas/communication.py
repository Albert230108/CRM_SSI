from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CommunicationCreate(BaseModel):
    channel: str
    direction: str = "outbound"
    message: str
    subject: str | None = None


class CommunicationRead(BaseModel):
    id: int
    tenant_id: int
    channel: str
    direction: str
    subject: str | None = None
    message: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
