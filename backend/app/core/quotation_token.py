"""Scoped, short-lived JWT used to hand off tenant/booking context to the
separate Quotation Manager service (quotation-manager/). Deliberately signed
with its own secret (QUOTATION_TOKEN_SECRET), distinct from the CRM's login
SECRET_KEY (app.core.security), so a compromise of the quotation-manager
service can never be used to forge a full CRM login session.
"""

import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

QUOTATION_TOKEN_SECRET = os.getenv("QUOTATION_TOKEN_SECRET")
if not QUOTATION_TOKEN_SECRET:
    raise RuntimeError("QUOTATION_TOKEN_SECRET must be set in the environment")

QUOTATION_TOKEN_ALGORITHM = "HS256"
QUOTATION_TOKEN_SCOPE = "quotation"
QUOTATION_TOKEN_EXPIRE_MINUTES = int(os.getenv("QUOTATION_TOKEN_EXPIRE_MINUTES", "60"))

_bearer_scheme = HTTPBearer(auto_error=True)


class QuotationTokenPayload(BaseModel):
    scope: str
    tenant_id: int
    booking_id: str | None
    issued_by_user_id: int


def create_quotation_token(
    tenant_id: int,
    booking_id: str | None,
    issued_by_user_id: int,
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        minutes=expires_minutes if expires_minutes is not None else QUOTATION_TOKEN_EXPIRE_MINUTES
    )
    to_encode = {
        "scope": QUOTATION_TOKEN_SCOPE,
        "tenant_id": tenant_id,
        "booking_id": booking_id,
        "sub": str(issued_by_user_id),
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(to_encode, QUOTATION_TOKEN_SECRET, algorithm=QUOTATION_TOKEN_ALGORITHM)


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
