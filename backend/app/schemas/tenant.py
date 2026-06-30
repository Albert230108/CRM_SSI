from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TenantCreate(BaseModel):
    booking_id: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    booking_status: str | None = None
    name: str
    responsible_comm: str | None = None


class TenantRead(BaseModel):
    id: int
    booking_id: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    booking_status: str | None = None
    name: str
    responsible_comm: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
