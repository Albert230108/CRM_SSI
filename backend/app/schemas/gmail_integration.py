from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GmailAccountCreate(BaseModel):
    email_address: str
    display_name: str | None = None
    credentials_json: dict


class GmailAccountRead(BaseModel):
    id: int
    email_address: str
    display_name: str | None = None
    is_active: bool
    last_synced_at: datetime | None = None
    last_history_id: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ConversationMessageRead(BaseModel):
    id: int
    provider: str
    provider_message_id: str
    direction: str
    sender_email: str | None = None
    recipient_email: str | None = None
    subject: str | None = None
    body: str
    sent_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ConversationRead(BaseModel):
    id: int
    provider: str
    provider_account_id: int | None = None
    provider_thread_id: str
    tenant_id: int | None = None
    subject: str | None = None
    last_message_at: datetime | None = None
    preview_text: str | None = None
    messages: list[ConversationMessageRead]
    model_config = ConfigDict(from_attributes=True)

