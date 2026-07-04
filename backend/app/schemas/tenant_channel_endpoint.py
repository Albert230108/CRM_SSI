from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class TenantChannelEndpointBase(BaseModel):
    tenant_id: int | None = None
    channel_type: str
    provider: str
    external_account_id: str | None = None
    external_phone_id: str | None = None
    external_chat_namespace: str | None = None
    webhook_token: str | None = None
    signing_secret: str | None = None
    is_active: bool = True

    @field_validator("channel_type", "provider")
    @classmethod
    def _required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class TenantChannelEndpointCreate(TenantChannelEndpointBase):
    tenant_id: int


class TenantChannelEndpointUpdate(BaseModel):
    tenant_id: int | None = None
    channel_type: str | None = None
    provider: str | None = None
    external_account_id: str | None = None
    external_phone_id: str | None = None
    external_chat_namespace: str | None = None
    webhook_token: str | None = None
    signing_secret: str | None = None
    is_active: bool | None = None


class TenantChannelEndpointRead(BaseModel):
    id: int
    tenant_id: int
    channel_type: str
    provider: str
    external_account_id: str | None = None
    external_phone_id: str | None = None
    external_chat_namespace: str | None = None
    webhook_token: str | None = None
    signing_secret: str | None = None
    is_active: bool
    routing_strategy: str
    has_webhook_token: bool
    has_signing_secret: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
