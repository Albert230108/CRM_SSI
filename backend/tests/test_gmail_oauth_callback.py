from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
from jose import jwt

from app.core.security import ALGORITHM, SECRET_KEY
from app.main import app


class _FakeResp(dict):
    def __init__(self, status):
        super().__init__()
        self.status = status
        self.reason = "Error"


class _FakeFlow:
    """Stand-in for google_auth_oauthlib.flow.Flow: skips the real token exchange HTTP call."""

    def __init__(self):
        self.redirect_uri = None
        self.code_verifier = None
        self.credentials = object()

    def fetch_token(self, code):
        pass


def _make_state(account_id=None):
    return jwt.encode(
        {
            "sub": "1",
            "account_id": account_id,
            "nonce": "test-nonce",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def test_oauth_callback_returns_429_when_gmail_still_rate_limited_after_retries(monkeypatch):
    """Regression test: a Gmail 429 from the getProfile lookup during account linking must
    surface as a clear 429, not an opaque 500 - and must not corrupt the PKCE verifier state
    for the caller in a way that produces the misleading "Missing OAuth PKCE code verifier"
    error seen when a failed callback gets retried.
    """
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://example.invalid/callback")

    state = _make_state()
    monkeypatch.setattr("app.api.gmail_integration._build_flow", lambda state=None: _FakeFlow())
    monkeypatch.setattr("app.api.gmail_integration._pop_oauth_code_verifier", lambda state: "fake-verifier")

    def fake_gmail_profile(credentials):
        raise HttpError(_FakeResp(429), b'{"error": {"message": "User Rate Limit Exceeded"}}')

    monkeypatch.setattr("app.api.gmail_integration._gmail_profile", fake_gmail_profile)

    with TestClient(app) as client:
        response = client.get(
            "/api/integrations/gmail/oauth/callback",
            params={"code": "fake-code", "state": state},
        )

    assert response.status_code == 429
    assert "rate-limiting" in response.json()["detail"].lower()


def test_oauth_callback_returns_502_for_non_rate_limit_gmail_errors(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://example.invalid/callback")

    state = _make_state()
    monkeypatch.setattr("app.api.gmail_integration._build_flow", lambda state=None: _FakeFlow())
    monkeypatch.setattr("app.api.gmail_integration._pop_oauth_code_verifier", lambda state: "fake-verifier")

    def fake_gmail_profile(credentials):
        raise HttpError(_FakeResp(500), b'{"error": {"message": "Internal error"}}')

    monkeypatch.setattr("app.api.gmail_integration._gmail_profile", fake_gmail_profile)

    with TestClient(app) as client:
        response = client.get(
            "/api/integrations/gmail/oauth/callback",
            params={"code": "fake-code", "state": state},
        )

    assert response.status_code == 502
