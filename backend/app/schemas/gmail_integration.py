from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.services.email_quote_strip import strip_quoted_reply


class GmailOAuthStartRead(BaseModel):
    authorization_url: str


class GmailAccountCreate(BaseModel):
    email_address: str
    display_name: str | None = None
    credentials_json: dict | None = None


class GmailAccountRead(BaseModel):
    id: int
    email_address: str
    display_name: str | None = None
    google_account_id: str | None = None
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
    raw_payload: dict[str, Any] | None = Field(default=None, exclude=True)
    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[misc]
    @property
    def body_display(self) -> str:
        """Body with quoted thread history stripped, for UI display."""
        return strip_quoted_reply(self.body)

    @computed_field  # type: ignore[misc]
    @property
    def body_html(self) -> str | None:
        """HTML rendition of the body, if Gmail provided one, for formatted display."""
        if not isinstance(self.raw_payload, dict):
            return None
        html = self.raw_payload.get("body_html")
        return html or None


class ConversationRead(BaseModel):
    id: int
    provider: str
    provider_account_id: int | None = None
    provider_account_email: str | None = None
    provider_account_display_name: str | None = None
    provider_thread_id: str
    tenant_id: int | None = None
    subject: str | None = None
    last_message_at: datetime | None = None
    preview_text: str | None = None
    messages: list[ConversationMessageRead]
    model_config = ConfigDict(from_attributes=True)
