from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    email: str
    full_name: str | None = None
    is_active: bool = True
    is_admin: bool = False


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: str | None = None
    full_name: str | None = None
    password: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None


class UserRead(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
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
    full_name: str | None = None
    password: str
    password_confirmation: str


class PasswordResetComplete(BaseModel):
    password: str
    password_confirmation: str
