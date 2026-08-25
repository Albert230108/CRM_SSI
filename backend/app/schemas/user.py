import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserBase(BaseModel):
    email: str
    full_name: str | None = None
    phone: str | None = None
    is_active: bool = True
    is_admin: bool = False


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    password: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None
    default_gmail_account_id: int | None = None
    default_whatsapp_account_id: str | None = None


class UserRead(UserBase):
    id: int
    whatsapp_notifications_enabled: bool = False
    default_gmail_account_id: int | None = None
    default_whatsapp_account_id: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TenantStatusFilterRead(BaseModel):
    statuses: list[str] | None = None


class TenantStatusFilterUpdate(BaseModel):
    statuses: list[str]


class PinnedTenantsRead(BaseModel):
    tenant_ids: list[int] | None = None


class PinnedTenantsUpdate(BaseModel):
    tenant_ids: list[int]


class AdminInviteCreate(BaseModel):
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    role: str = "non-admin"

    @field_validator('role')
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {'admin', 'non-admin'}:
            raise ValueError('Role must be admin or non-admin')
        return normalized


class AdminInviteRead(BaseModel):
    id: int
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    role: str
    status: str
    invite_url: str | None = None
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    invited_by_user_id: int
    model_config = ConfigDict(from_attributes=True)


class InvitationComplete(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    password: str
    password_confirmation: str


class PasswordResetComplete(BaseModel):
    password: str
    password_confirmation: str


class AdminUserCreate(BaseModel):
    email: str
    full_name: str | None = None
    phone: str | None = None
    is_admin: bool = False
    password: str
    password_confirmation: str

    @field_validator('email')
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError('Invalid email address')
        return normalized

    @field_validator('password')
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError('Password must be at least 8 characters long')
        return value


class UserDeleteResult(BaseModel):
    id: int
    deleted: bool


class AdminInviteClearResult(BaseModel):
    revoked_count: int