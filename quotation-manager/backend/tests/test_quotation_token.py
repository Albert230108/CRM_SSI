from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.quotation_token import QUOTATION_TOKEN_ALGORITHM, decode_quotation_token
from tests.conftest import make_quotation_token


def test_decode_valid_token():
    token = make_quotation_token(tenant_id=42, booking_id="99999", issued_by_user_id=7)
    payload = decode_quotation_token(token)
    assert payload.tenant_id == 42
    assert payload.booking_id == "99999"
    assert payload.issued_by_user_id == 7
    assert payload.scope == "quotation"


def test_decode_rejects_expired_token():
    now = datetime.now(timezone.utc)
    token = make_quotation_token(iat=now - timedelta(hours=2), exp=now - timedelta(hours=1))
    with pytest.raises(HTTPException) as exc_info:
        decode_quotation_token(token)
    assert exc_info.value.status_code == 401


def test_decode_rejects_wrong_scope():
    token = make_quotation_token(scope="something-else")
    with pytest.raises(HTTPException) as exc_info:
        decode_quotation_token(token)
    assert exc_info.value.status_code == 401


def test_decode_rejects_wrong_secret():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "scope": "quotation",
            "tenant_id": 1,
            "booking_id": "1",
            "sub": "1",
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        "a-different-secret",
        algorithm=QUOTATION_TOKEN_ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_quotation_token(token)
    assert exc_info.value.status_code == 401
