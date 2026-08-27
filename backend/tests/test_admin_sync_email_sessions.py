from types import SimpleNamespace
import asyncio

from app.api import admin_sync
from app.models.gmail_integration import GmailAccount


class _FakeQuery:
    def __init__(self, results):
        self._results = list(results)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._results)

    def first(self):
        return self._results[0] if self._results else None


class _FakeSession:
    def __init__(self, account=None, accounts=None):
        self._account = account
        self._accounts = list(accounts or [])
        self.closed = False
        self.rolled_back = False

    def query(self, model):
        assert model is GmailAccount
        if self._account is not None:
            return _FakeQuery([self._account])
        return _FakeQuery(self._accounts)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_sync_emails_uses_a_fresh_session_per_account(monkeypatch):
    outer_accounts = [SimpleNamespace(id=11), SimpleNamespace(id=22)]
    outer_db = _FakeSession(accounts=outer_accounts)

    helper_sessions = [_FakeSession(account=outer_accounts[0]), _FakeSession(account=outer_accounts[1])]
    created_sessions = []

    def fake_session_factory():
        session = helper_sessions[len(created_sessions)]
        created_sessions.append(session)
        return session

    sync_calls = []

    def fake_sync_gmail_account(db, account, tenant_ids=None):
        sync_calls.append((db, account.id, tenant_ids))
        assert db is not outer_db
        return 7

    async def fake_run_in_threadpool(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(admin_sync, "SessionLocal", fake_session_factory)
    monkeypatch.setattr(admin_sync, "_sync_gmail_account", fake_sync_gmail_account)
    monkeypatch.setattr(admin_sync, "run_in_threadpool", fake_run_in_threadpool)

    imported = asyncio.run(admin_sync._sync_emails(outer_db, tenant_ids=[99]))

    assert imported == 14
    assert sync_calls == [
        (helper_sessions[0], 11, [99]),
        (helper_sessions[1], 22, [99]),
    ]
    assert created_sessions == helper_sessions
    assert all(session.closed for session in helper_sessions)
    assert not outer_db.closed
