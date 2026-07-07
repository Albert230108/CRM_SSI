from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CommunicationCreate(BaseModel):
    channel: str
    direction: str = "outbound"
    message: str
    subject: str | None = None
    whatsapp_endpoint_id: int | None = None
    external_account_id: str | None = None


class CommunicationRead(BaseModel):
    id: int
    tenant_id: int
    channel: str
    direction: str
    provider: str | None = None
    external_account_id: str | None = None
    external_phone_id: str | None = None
    external_chat_namespace: str | None = None
    whatsapp_chat_id: str | None = None
    whatsapp_identity_key: str | None = None
    whatsapp_normalized_phone: str | None = None
    provider_message_id: str | None = None
    subject: str | None = None
    message: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
