from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


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


class UserRead(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


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


class InviteCreate(BaseModel):
    email: str
    full_name: str | None = None
    is_admin: bool = False


class InviteRead(BaseModel):
    token: str
    invite_url: str


class PasswordResetRequestCreate(BaseModel):
    user_id: int


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