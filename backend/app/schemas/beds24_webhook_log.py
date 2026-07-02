from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Beds24WebhookLogRead(BaseModel):
    id: int
    provider: str
    received_at: datetime
    processed_at: datetime | None = None
    dedupe_key: str
    external_event_id: str | None = None
    event_type: str | None = None
    status: str
    booking_id: str | None = None
    room_id: str | None = None
    tenant_id: int | None = None
    http_status: int | None = None
    result_message: str | None = None
    error_summary: str | None = None
    error_traceback: str | None = None
    raw_payload: dict[str, Any]
    parsed_fields: dict[str, Any] | None = None
    model_config = ConfigDict(from_attributes=True)
