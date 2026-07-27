"""Verifies the scoped JWT minted by the CRM backend (app.core.quotation_token
on the CRM side). This service never mints tokens itself - it only validates
the ones the CRM hands the browser, and forwards the same raw token string
when calling back into the CRM's proxy endpoints (see services/crm_client.py).
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import QUOTATION_TOKEN_SECRET

QUOTATION_TOKEN_ALGORITHM = "HS256"
QUOTATION_TOKEN_SCOPE = "quotation"

_bearer_scheme = HTTPBearer(auto_error=True)


class QuotationTokenPayload(BaseModel):
    scope: str
    tenant_id: int
    booking_id: str | None
    issued_by_user_id: int


def decode_quotation_token(token: str) -> QuotationTokenPayload:
    invalid_token_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired quotation token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, QUOTATION_TOKEN_SECRET, algorithms=[QUOTATION_TOKEN_ALGORITHM])
    except JWTError as exc:
        raise invalid_token_exception from exc

    if payload.get("scope") != QUOTATION_TOKEN_SCOPE:
        raise invalid_token_exception

    tenant_id = payload.get("tenant_id")
    issued_by_user_id = payload.get("sub")
    if tenant_id is None or issued_by_user_id is None:
        raise invalid_token_exception

    return QuotationTokenPayload(
        scope=payload["scope"],
        tenant_id=int(tenant_id),
        booking_id=payload.get("booking_id"),
        issued_by_user_id=int(issued_by_user_id),
    )


def verify_quotation_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> QuotationTokenPayload:
    return decode_quotation_token(credentials.credentials)


def get_raw_token(credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme)) -> str:
    """Raw bearer token string, for crm_client.py to forward unchanged to the CRM backend."""
    return credentials.credentials
