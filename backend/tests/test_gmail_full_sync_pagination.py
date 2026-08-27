import base64

import app.api.gmail_integration as gmail_integration
from app.models.gmail_integration import ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_email_address import TenantEmailAddress


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _message(message_id: str, from_address: str, to_address: str) -> dict:
    return {
        "id": message_id,
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": from_address},
                {"name": "To", "value": to_address},
                {"name": "Subject", "value": "Booking question"},
            ],
            "body": {"data": _encode("Hi there")},
        },
    }


class _Executable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeThreadsService:
    """Chainable stand-in scoped to what full/backfill syncs call: users().threads().list()
    (paginated via pageToken) and users().threads().get()."""

    def __init__(self, *, list_pages, threads_by_id):
        self._list_pages = list(list_pages)
        self._threads_by_id = threads_by_id
        self.list_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def users(self):
        return self

    def threads(self):
        return self

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return _Executable(self._list_pages.pop(0))

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return _Executable(self._threads_by_id[kwargs["id"]])


def test_sync_gmail_account_paginates_beyond_first_page_of_threads(db_session, monkeypatch):
    """Regression test: _sync_gmail_account used to call threads().list() with no pageToken
    loop, so any account/tenant-query combination matching more than one page of threads
    silently dropped everything past the first page on every manual sync / admin sync-all /
    bootstrap resync."""
    account = GmailAccount(email_address="full-sync-account@example.com", is_active=True)
    tenant = Tenant(name="Paginated Tenant", booking_id="booking-paginated")
    db_session.add_all([account, tenant])
    db_session.commit()
    # Reachability comes from the CRM_EMAIL link, which is what the search query is built from.
    db_session.add(TenantEmailAddress(tenant_id=tenant.id, email="guest@example.com", is_active=True))
    db_session.commit()

    fake_service = _FakeThreadsService(
        list_pages=[
            {"threads": [{"id": "thread-1"}], "nextPageToken": "page-2"},
            {"threads": [{"id": "thread-2"}]},
        ],
        threads_by_id={
            "thread-1": {
                "id": "thread-1",
                "messages": [_message("msg-1", "guest@example.com", "full-sync-account@example.com")],
            },
            "thread-2": {
                "id": "thread-2",
                "messages": [_message("msg-2", "guest@example.com", "full-sync-account@example.com")],
            },
        },
    )
    monkeypatch.setattr(gmail_integration, "_build_service_for_account", lambda acct: fake_service)

    saved = gmail_integration._sync_gmail_account(db_session, account)

    assert saved == 2
    assert len(fake_service.list_calls) == 2
    assert fake_service.list_calls[0]["pageToken"] is None
    assert fake_service.list_calls[1]["pageToken"] == "page-2"
    assert {m.provider_message_id for m in db_session.query(ConversationMessage).all()} == {"msg-1", "msg-2"}


def test_sync_gmail_account_includes_active_secondary_email_in_query(db_session, monkeypatch):
    """The full-sync search query covers every active CRM_EMAIL link a tenant has, not just
    the first one."""
    account = GmailAccount(email_address="alias-sync-account@example.com", is_active=True)
    tenant = Tenant(name="Alias Tenant", booking_id="booking-alias-tenant")
    db_session.add_all([account, tenant])
    db_session.commit()
    db_session.add_all([
        TenantEmailAddress(tenant_id=tenant.id, email="primary@example.com", is_active=True),
        TenantEmailAddress(tenant_id=tenant.id, email="alias@example.com", is_active=True),
    ])
    db_session.commit()

    fake_service = _FakeThreadsService(list_pages=[{"threads": []}], threads_by_id={})
    monkeypatch.setattr(gmail_integration, "_build_service_for_account", lambda acct: fake_service)

    gmail_integration._sync_gmail_account(db_session, account)

    assert len(fake_service.list_calls) == 1
    query = fake_service.list_calls[0]["q"]
    assert '"primary@example.com"' in query
    assert '"alias@example.com"' in query


def test_sync_gmail_account_reports_thread_progress_across_query_chunks(db_session, monkeypatch):
    account = GmailAccount(email_address="chunked-sync-account@example.com", is_active=True)
    tenant = Tenant(name="Chunked Tenant", booking_id="booking-chunked-tenant")
    db_session.add_all([account, tenant])
    db_session.commit()
    db_session.add_all([
        TenantEmailAddress(tenant_id=tenant.id, email="a@example.com", is_active=True),
        TenantEmailAddress(tenant_id=tenant.id, email="b@example.com", is_active=True),
        TenantEmailAddress(tenant_id=tenant.id, email="c@example.com", is_active=True),
    ])
    db_session.commit()

    fake_service = _FakeThreadsService(
        list_pages=[
            {"threads": [{"id": "thread-1"}]},
            {"threads": [{"id": "thread-2"}]},
            {"threads": [{"id": "thread-3"}]},
        ],
        threads_by_id={
            "thread-1": {"id": "thread-1", "messages": [_message("msg-1", "a@example.com", "chunked-sync-account@example.com")]},
            "thread-2": {"id": "thread-2", "messages": [_message("msg-2", "b@example.com", "chunked-sync-account@example.com")]},
            "thread-3": {"id": "thread-3", "messages": [_message("msg-3", "c@example.com", "chunked-sync-account@example.com")]},
        },
    )
    progress_updates: list[tuple[int, int]] = []

    monkeypatch.setattr(gmail_integration, "_build_service_for_account", lambda acct: fake_service)
    monkeypatch.setattr(gmail_integration, "GMAIL_ACCOUNT_SYNC_QUERY_CHUNK_SIZE", 1)

    saved = gmail_integration._sync_gmail_account(
        db_session,
        account,
        progress=lambda current, total: progress_updates.append((current, total)),
    )

    assert saved == 3
    assert progress_updates == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert len(fake_service.list_calls) == 3
    assert {m.provider_message_id for m in db_session.query(ConversationMessage).all()} == {"msg-1", "msg-2", "msg-3"}


def test_sync_gmail_account_for_email_paginates_beyond_first_page(db_session, monkeypatch):
    """Same pagination gap as _sync_gmail_account, but in the narrow one-off search fired
    when a tenant links a new email address."""
    account = GmailAccount(email_address="narrow-sync-account@example.com", is_active=True)
    db_session.add(account)
    db_session.commit()

    fake_service = _FakeThreadsService(
        list_pages=[
            {"threads": [{"id": "thread-a"}], "nextPageToken": "page-2"},
            {"threads": [{"id": "thread-b"}]},
        ],
        threads_by_id={
            "thread-a": {
                "id": "thread-a",
                "messages": [_message("msg-a", "linked@example.com", "narrow-sync-account@example.com")],
            },
            "thread-b": {
                "id": "thread-b",
                "messages": [_message("msg-b", "linked@example.com", "narrow-sync-account@example.com")],
            },
        },
    )
    monkeypatch.setattr(gmail_integration, "_build_service_for_account", lambda acct: fake_service)

    gmail_integration.sync_gmail_account_for_email(db_session, account, "linked@example.com")

    assert len(fake_service.list_calls) == 2
    assert fake_service.list_calls[1]["pageToken"] == "page-2"
    assert {m.provider_message_id for m in db_session.query(ConversationMessage).all()} == {"msg-a", "msg-b"}
