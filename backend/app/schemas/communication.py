from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CommunicationRead(BaseModel):
    id: int
    tenant_id: int
    channel: str
    subject: str | None = None
    message: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
