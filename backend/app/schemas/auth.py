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
    model_config = ConfigDict(from_attributes=True)
