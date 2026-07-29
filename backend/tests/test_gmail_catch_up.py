import base64

from app.api.gmail_integration import _catch_up_gmail_account
from app.models.gmail_integration import ConversationMessage, GmailAccount


def _simple_message(message_id: str, thread_id: str, *, sender: str = "tenant@example.com") -> dict:
    return {
        "id": message_id,
        "threadId": thread_id,
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": "info@shortstayinn.com"},
                {"name": "Subject", "value": "Hello"},
            ],
            "body": {"data": base64.urlsafe_b64encode(b"Hi there").decode("utf-8")},
        },
    }


class _Executable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeGmailService:
    """Chainable stand-in scoped to what the catch-up path calls: getProfile(),
    users().history().list(), and users().threads().get()."""

    def __init__(self, *, profile, history_pages=None, threads_by_id=None, failing_thread_ids=None):
        self._profile = profile
        self._history_pages = list(history_pages or [])
        self._threads_by_id = threads_by_id or {}
        self._failing_thread_ids = failing_thread_ids or set()
        self.get_profile_calls: list[dict] = []
        self.history_list_calls: list[dict] = []
        self.threads_get_calls: list[dict] = []

    def users(self):
        return self

    def history(self):
        return self

    def threads(self):
        return self

    def getProfile(self, **kwargs):  # noqa: N802 - matches Gmail API's method name
        self.get_profile_calls.append(kwargs)
        return _Executable(self._profile)

    def list(self, **kwargs):
        self.history_list_calls.append(kwargs)
        page = self._history_pages.pop(0)
        return _Executable(page)

    def get(self, **kwargs):
        self.threads_get_calls.append(kwargs)
        thread_id = kwargs["id"]
        if thread_id in self._failing_thread_ids:
            raise RuntimeError(f"simulated fetch failure for thread {thread_id}")
        return _Executable(self._threads_by_id[thread_id])


def test_catch_up_is_noop_when_history_id_unchanged(db_session, monkeypatch):
    account = GmailAccount(email_address="info@shortstayinn.com", is_active=True, last_history_id="500")
    db_session.add(account)
    db_session.commit()
    previous_synced_at = account.last_synced_at

    fake_service = _FakeGmailService(profile={"historyId": "500"})
    monkeypatch.setattr("app.api.gmail_integration._build_service_for_account", lambda acct: fake_service)

    _catch_up_gmail_account(db_session, account)

    assert fake_service.history_list_calls == []
    assert fake_service.threads_get_calls == []
    db_session.refresh(account)
    assert account.last_history_id == "500"
    assert account.last_synced_at is not None
    assert account.last_synced_at != previous_synced_at


def test_catch_up_bootstraps_via_full_sync_when_no_history_cursor(db_session, monkeypatch):
    account = GmailAccount(email_address="info@shortstayinn.com", is_active=True, last_history_id=None)
    db_session.add(account)
    db_session.commit()

    fake_service = _FakeGmailService(profile={"historyId": "700"})
    full_sync_calls = []

    def fake_full_sync(db, acct):
        full_sync_calls.append(acct.id)
        return 0

    monkeypatch.setattr("app.api.gmail_integration._build_service_for_account", lambda acct: fake_service)
    monkeypatch.setattr("app.api.gmail_integration._sync_gmail_account", fake_full_sync)

    _catch_up_gmail_account(db_session, account)

    assert full_sync_calls == [account.id]
    db_session.refresh(account)
    assert account.last_history_id == "700"


def test_catch_up_delegates_incremental_sync_when_history_id_changed(db_session, monkeypatch):
    account = GmailAccount(email_address="info@shortstayinn.com", is_active=True, last_history_id="100")
    db_session.add(account)
    db_session.commit()

    thread = {"id": "thread-1", "messages": [_simple_message("msg-1", "thread-1")]}
    fake_service = _FakeGmailService(
        profile={"historyId": "150"},
        history_pages=[{"history": [{"id": "150", "messagesAdded": [{"message": {"id": "msg-1", "threadId": "thread-1"}}]}]}],
        threads_by_id={"thread-1": thread},
    )
    monkeypatch.setattr("app.api.gmail_integration._build_service_for_account", lambda acct: fake_service)

    _catch_up_gmail_account(db_session, account)

    assert fake_service.history_list_calls[0]["startHistoryId"] == "100"
    db_session.refresh(account)
    assert account.last_history_id == "150"

    message = db_session.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "msg-1").first()
    assert message is not None
    assert message.sender_email == "tenant@example.com"


def test_catch_up_skips_failing_thread_but_still_advances_cursor_for_others(db_session, monkeypatch):
    """Regression test: a single thread failing while processing a history-notification batch
    used to propagate out of _process_gmail_history_notification entirely, so last_history_id
    was never advanced - meaning every *other* thread in that same batch got silently retried
    forever right along with the one actually failing.
    """
    account = GmailAccount(email_address="info@shortstayinn.com", is_active=True, last_history_id="100")
    db_session.add(account)
    db_session.commit()

    good_thread = {"id": "thread-good", "messages": [_simple_message("msg-good", "thread-good")]}
    fake_service = _FakeGmailService(
        profile={"historyId": "150"},
        history_pages=[
            {
                "history": [
                    {
                        "id": "150",
                        "messagesAdded": [
                            {"message": {"id": "msg-bad", "threadId": "thread-bad"}},
                            {"message": {"id": "msg-good", "threadId": "thread-good"}},
                        ],
                    }
                ]
            }
        ],
        threads_by_id={"thread-good": good_thread},
        failing_thread_ids={"thread-bad"},
    )
    monkeypatch.setattr("app.api.gmail_integration._build_service_for_account", lambda acct: fake_service)

    _catch_up_gmail_account(db_session, account)

    db_session.refresh(account)
    # Cursor must still advance even though thread-bad failed, otherwise thread-good (and
    # everything else in this batch) would be re-fetched and re-processed every cycle forever.
    assert account.last_history_id == "150"

    message = db_session.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "msg-good").first()
    assert message is not None
