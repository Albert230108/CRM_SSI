from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StoredAttachmentRead(BaseModel):
    id: int
    filename: str
    mime_type: str | None = None
    size_bytes: int
    origin: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
