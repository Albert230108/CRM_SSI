from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class TenantEmailLinkCreate(BaseModel):
    email: str
    confirm_conflict: bool = False

    @field_validator("email")
    @classmethod
    def _required_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not value or "@" not in value:
            raise ValueError("must be a valid email address")
        return value


class TenantEmailLinkRead(BaseModel):
    id: int
    tenant_id: int
    email: str
    beds24_sync_status: str
    source: str
    is_active: bool
    linked_by_user_id: int | None = None
    unlinked_at: datetime | None = None
    unlinked_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TenantEmailLinkCreateRead(BaseModel):
    link: TenantEmailLinkRead
    gmail_sync_job_id: str | None = None


class TenantEmailLinkDeleteRead(BaseModel):
    link: TenantEmailLinkRead
    deleted_conversations: int = 0
    shared_conversations_unlinked: int = 0
