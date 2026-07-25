from datetime import datetime

from pydantic import BaseModel


class AiAutoDraftRead(BaseModel):
    id: int
    tenant_id: int
    tenant_name: str | None = None
    channel: str
    template_id: int | None = None
    generated_text: str
    status: str
    scheduled_send_at: datetime | None = None
    created_at: datetime
