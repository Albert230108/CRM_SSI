from pydantic import BaseModel


class TenantAiSettingsRead(BaseModel):
    tenant_id: int
    available_template_ids: list[int]
    default_email_template_id: int | None = None
    default_whatsapp_template_id: int | None = None
    auto_draft_email: bool
    auto_draft_whatsapp: bool
    auto_send_email: bool
    auto_send_whatsapp: bool


class TenantAiSettingsUpdate(BaseModel):
    available_template_ids: list[int] = []
    default_email_template_id: int | None = None
    default_whatsapp_template_id: int | None = None
    auto_draft_email: bool = False
    auto_draft_whatsapp: bool = False
    auto_send_email: bool = False
    auto_send_whatsapp: bool = False
