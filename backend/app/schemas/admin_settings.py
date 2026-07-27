from pydantic import BaseModel, ConfigDict


class AdminSettingsRead(BaseModel):
    forward_to_email: str | None = None
    ai_draft_debounce_seconds: int
    ai_auto_send_delay_seconds: int
    ai_auto_apply_templates_to_new_tenants: bool
    model_config = ConfigDict(from_attributes=True)


class AdminSettingsUpdate(BaseModel):
    forward_to_email: str | None = None
    ai_draft_debounce_seconds: int | None = None
    ai_auto_send_delay_seconds: int | None = None
    ai_auto_apply_templates_to_new_tenants: bool | None = None
