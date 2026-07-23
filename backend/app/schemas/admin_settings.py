from pydantic import BaseModel, ConfigDict


class AdminSettingsRead(BaseModel):
    forward_to_email: str | None = None
    model_config = ConfigDict(from_attributes=True)


class AdminSettingsUpdate(BaseModel):
    forward_to_email: str | None = None
