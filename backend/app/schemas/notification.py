from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    id: int
    tenant_id: int | None = None
    tenant_name: str | None = None
    channel: str
    direction: str
    preview: str | None = None
    created_at: datetime
    is_read: bool
    model_config = ConfigDict(from_attributes=True)
