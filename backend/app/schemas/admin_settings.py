from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminSettingsRead(BaseModel):
    forward_to_email: str | None = None
    ai_draft_debounce_seconds: int
    ai_auto_send_delay_seconds: int
    ai_auto_apply_templates_to_new_tenants: bool
    planner_default_mode: str = "off"
    brain_writer_default_enabled: bool = False
    action_writer_default_enabled: bool = False
    formatter_default_enabled: bool = False
    ai_daily_token_cap: int | None = None
    notification_whatsapp_debounce_seconds: int
    notification_whatsapp_external_account_id: str | None = None
    model_config = ConfigDict(from_attributes=True)


class AdminSettingsUpdate(BaseModel):
    forward_to_email: str | None = None
    ai_draft_debounce_seconds: int | None = None
    ai_auto_send_delay_seconds: int | None = None
    ai_auto_apply_templates_to_new_tenants: bool | None = None
    planner_default_mode: Literal["off", "manual", "auto-draft", "auto-send"] | None = None
    brain_writer_default_enabled: bool | None = None
    action_writer_default_enabled: bool | None = None
    formatter_default_enabled: bool | None = None
    ai_daily_token_cap: int | None = Field(default=None, ge=0)
    notification_whatsapp_debounce_seconds: int | None = None
    notification_whatsapp_external_account_id: str | None = None
    clear_notification_whatsapp_external_account_id: bool = False
