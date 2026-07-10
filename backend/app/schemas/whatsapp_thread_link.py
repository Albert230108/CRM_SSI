from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class WhatsAppAccountRead(BaseModel):
    external_account_id: str
    provider: str
    label: str


class WhatsAppChatRead(BaseModel):
    chat_id: str
    chat_name: str | None = None
    provider: str
    external_account_id: str
    last_message_timestamp: datetime | None = None
    last_message_preview: str | None = None
    already_linked: bool = False
    linked_thread_id: int | None = None


class ThreadWhatsAppLinkCreate(BaseModel):
    provider: str
    external_account_id: str
    chat_id: str
    chat_display_name: str | None = None
    replace_existing: bool = False

    @field_validator("provider", "external_account_id", "chat_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ThreadWhatsAppLinkRead(BaseModel):
    id: int
    thread_id: int
    provider: str
    external_account_id: str
    chat_id: str
    chat_display_name: str | None = None
    is_active: bool
    linked_by_user_id: int | None = None
    unlinked_at: datetime | None = None
    unlinked_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WhatsAppChatResyncResult(BaseModel):
    ok: bool
    fetched: int = 0
    imported: int = 0
    deduped: int = 0
    failed: int = 0
    error: str | None = None


class ThreadWhatsAppLinkResyncRead(BaseModel):
    link: ThreadWhatsAppLinkRead
    resync: WhatsAppChatResyncResult
