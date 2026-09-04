from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class WhatsAppAccountRead(BaseModel):
    external_account_id: str
    provider: str
    label: str


class WhatsAppAccountStatusRead(BaseModel):
    external_account_id: str
    label: str
    provider: str
    # reachable=False means the service instance itself could not be contacted; ready is then None.
    reachable: bool
    ready: bool | None = None
    client_id: str | None = None
    last_ready_at: datetime | None = None
    last_disconnect: dict | None = None
    last_auth_failure_at: datetime | None = None
    has_qr: bool = False
    # Reconnect health. auto_reconnect_paused means the service gave up re-linking after repeated
    # LOGOUTs and is waiting for a human (re-scan the QR, or POST /admin/reconnect).
    consecutive_logouts: int = 0
    auto_reconnect_paused: bool = False
    error: str | None = None


class WhatsAppAccountQrRead(BaseModel):
    external_account_id: str
    ready: bool
    qr_data_url: str | None = None
    message: str | None = None


class WhatsAppAccountLogsRead(BaseModel):
    external_account_id: str
    # available=False covers both "not running under systemd" and "journal unreadable"; the reason
    # is in message so the admin UI can explain itself instead of showing an empty box.
    available: bool
    unit: str | None = None
    lines: list[str] = []
    message: str | None = None


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
    replace_link_id: int | None = None

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
    skipped_no_content: int = 0
    failed: int = 0
    error: str | None = None
    throttled: bool = False


class ThreadWhatsAppLinkResyncRead(BaseModel):
    link: ThreadWhatsAppLinkRead
    resync: WhatsAppChatResyncResult


class ThreadWhatsAppResyncAllRead(BaseModel):
    results: list[ThreadWhatsAppLinkResyncRead]
