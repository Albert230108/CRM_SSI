from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeviceTokenRegister(BaseModel):
    token: str
    platform: str | None = None


class DeviceTokenUnregister(BaseModel):
    token: str


class DeviceTokenRead(BaseModel):
    id: int
    token: str
    platform: str | None = None
    created_at: datetime
    last_seen_at: datetime
    model_config = ConfigDict(from_attributes=True)
