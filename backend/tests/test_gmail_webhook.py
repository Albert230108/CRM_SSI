import base64
import json

from googleapiclient.errors import HttpError

from app.models.gmail_integration import ConversationMessage, GmailAccount


class _FakeResp:
    def __init__(self, status: int):
        self.status = status
        self.reason = "Not Found"


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


class _FakeGmailService:
    """Chainable stand-in for googleapiclient's Gmail service, scoped to what the
    incremental sync path calls: users().history().list() and users().threads().get()."""

    def __init__(self, *, history_pages=None, history_error=None, threads_by_id=None):
        self._history_pages = list(history_pages or [])
        self._history_error = history_error
        self._threads_by_id = threads_by_id or {}
        self.history_list_calls: list[dict] = []
        self.threads_get_calls: list[dict] = []

    def users(self):
        return self

    def history(self):
        return self

    def threads(self):
        return self

    def list(self, **kwargs):
        self.history_list_calls.append(kwargs)
        if self._history_error is not None:
            raise self._history_error
        page = self._history_pages.pop(0)
        return _Executable(page)

    def get(self, **kwargs):
        self.threads_get_calls.append(kwargs)
        return _Executable(self._threads_by_id[kwargs["id"]])


class _Executable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


def _notification_body(email_address: str, history_id: str) -> dict:
    data = base64.b64encode(json.dumps({"emailAddress": email_address, "historyId": history_id}).encode("utf-8"))
    return {"message": {"data": data.decode("utf-8"), "messageId": "1", "publishTime": "2026-07-16T00:00:00Z"}, "subscription": "projects/p/subscriptions/s"}


def test_webhook_rejects_wrong_secret(client, db_session, monkeypatch):
    monkeypatch.setenv("GMAIL_PUBSUB_WEBHOOK_SECRET", "correct-secret")
    response = client.post(
        "/webhooks/gmail?token=wrong-secret",
        json=_notification_body("info@shortstayinn.com", "200"),
    )
    assert response.status_code == 403


def test_webhook_rejects_missing_secret_config(client, db_session, monkeypatch):
    monkeypatch.delenv("GMAIL_PUBSUB_WEBHOOK_SECRET", raising=False)
    response = client.post(
        "/webhooks/gmail?token=anything",
        json=_notification_body("info@shortstayinn.com", "200"),
    )
    assert response.status_code == 403


def test_webhook_acks_unknown_account_without_error(client, db_session, monkeypatch):
    monkeypatch.setenv("GMAIL_PUBSUB_WEBHOOK_SECRET", "test-secret")
    response = client.post(
        "/webhooks/gmail?token=test-secret",
        json=_notification_body("nobody@shortstayinn.com", "200"),
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_processes_incremental_history_and_advances_cursor(client, db_session, monkeypatch):
    monkeypatch.setenv("GMAIL_PUBSUB_WEBHOOK_SECRET", "test-secret")

    account = GmailAccount(email_address="info@shortstayinn.com", is_active=True, last_history_id="100")
    db_session.add(account)
    db_session.commit()

    thread = {"id": "thread-1", "messages": [_simple_message("msg-1", "thread-1")]}
    fake_service = _FakeGmailService(
        history_pages=[{"history": [{"id": "150", "messagesAdded": [{"message": {"id": "msg-1", "threadId": "thread-1"}}]}]}],
        threads_by_id={"thread-1": thread},
    )
    monkeypatch.setattr("app.api.gmail_integration._build_service_for_account", lambda acct: fake_service)

    response = client.post(
        "/webhooks/gmail?token=test-secret",
        json=_notification_body("info@shortstayinn.com", "202"),
    )
    assert response.status_code == 200

    db_session.refresh(account)
    assert account.last_history_id == "202"
    assert fake_service.history_list_calls[0]["startHistoryId"] == "100"

    message = db_session.query(ConversationMessage).filter(ConversationMessage.provider_message_id == "msg-1").first()
    assert message is not None
    assert message.sender_email == "tenant@example.com"


def test_webhook_falls_back_to_full_sync_when_history_cursor_expired(client, db_session, monkeypatch):
    monkeypatch.setenv("GMAIL_PUBSUB_WEBHOOK_SECRET", "test-secret")

    account = GmailAccount(email_address="info@shortstayinn.com", is_active=True, last_history_id="stale")
    db_session.add(account)
    db_session.commit()

    fake_service = _FakeGmailService(history_error=HttpError(_FakeResp(404), b'{"error": {"message": "Not Found"}}'))
    full_sync_calls = []

    def fake_full_sync(db, acct):
        full_sync_calls.append(acct.id)
        return 0

    monkeypatch.setattr("app.api.gmail_integration._build_service_for_account", lambda acct: fake_service)
    monkeypatch.setattr("app.api.gmail_integration._sync_gmail_account", fake_full_sync)

    response = client.post(
        "/webhooks/gmail?token=test-secret",
        json=_notification_body("info@shortstayinn.com", "999"),
    )
    assert response.status_code == 200

    db_session.refresh(account)
    assert full_sync_calls == [account.id]
    assert account.last_history_id == "999"
