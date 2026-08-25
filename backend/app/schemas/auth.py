from pydantic import BaseModel, ConfigDict


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    sub: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class CurrentUser(BaseModel):
    id: int
    email: str
    full_name: str | None = None
    is_active: bool
    is_admin: bool
    whatsapp_notifications_enabled: bool = False
    default_gmail_account_id: int | None = None
    default_whatsapp_account_id: str | None = None
    model_config = ConfigDict(from_attributes=True)
