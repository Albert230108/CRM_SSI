import os

os.environ.setdefault("QUOTATION_TOKEN_SECRET", "test-quotation-secret")
os.environ.setdefault("CRM_BACKEND_URL", "http://backend.invalid")
os.environ.setdefault("TENANT_FILES_ROOT", "/tmp/quotation-manager-tests")

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.quotation_token import QUOTATION_TOKEN_ALGORITHM, QUOTATION_TOKEN_SECRET
from app.main import app


def make_quotation_token(tenant_id: int = 1, booking_id: str = "12345", issued_by_user_id: int = 1, **overrides) -> str:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    payload = {
        "scope": "quotation",
        "tenant_id": tenant_id,
        "booking_id": booking_id,
        "sub": str(issued_by_user_id),
        "iat": now,
        "exp": now + timedelta(minutes=60),
    }
    payload.update(overrides)
    return jwt.encode(payload, QUOTATION_TOKEN_SECRET, algorithm=QUOTATION_TOKEN_ALGORITHM)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers():
    return {"Authorization": f"Bearer {make_quotation_token()}"}
