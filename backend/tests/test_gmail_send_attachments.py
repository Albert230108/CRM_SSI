import base64
from email import message_from_bytes
from email.policy import default as default_policy

import pytest

from app.services import gmail_client
from app.services.attachment_service import OutboundAttachment


class _FakeSend:
    def __init__(self, captured):
        self._captured = captured

    def execute(self):
        return {"id": "sent-1", "threadId": self._captured["body"]["threadId"]}


class _FakeMessages:
    def __init__(self, captured):
        self._captured = captured

    def send(self, *, userId, body):
        self._captured["userId"] = userId
        self._captured["body"] = body
        return _FakeSend(self._captured)


class _FakeUsers:
    def __init__(self, captured):
        self._captured = captured

    def messages(self):
        return _FakeMessages(self._captured)


class _FakeService:
    def __init__(self, captured):
        self._captured = captured

    def users(self):
        return _FakeUsers(self._captured)


@pytest.fixture()
def captured_send(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(gmail_client, "build", lambda *a, **k: _FakeService(captured))
    yield captured


def _sent_mime(captured):
    raw = base64.urlsafe_b64decode(captured["body"]["raw"].encode("utf-8"))
    return message_from_bytes(raw, policy=default_policy)


def _send(attachments=(), *, cc_email=None, forward=False):
    sender = gmail_client.send_gmail_forward if forward else gmail_client.send_gmail_reply
    return sender(
        object(),
        thread_id="thread-1",
        to_email="guest@example.com",
        cc_email=cc_email,
        subject="Booking",
        body_text="Here you go.",
        from_email="crm@example.com",
        attachments=attachments,
    )


def test_send_without_attachments_stays_single_part(captured_send):
    _send()

    mime = _sent_mime(captured_send)
    assert not mime.is_multipart()
    assert mime.get_content_type() == "text/plain"
    assert mime.get_content().strip() == "Here you go."


def test_send_with_attachment_produces_multipart_mixed(captured_send):
    _send(
        [
            OutboundAttachment(
                attachment_id=1, filename="invoice.pdf", mime_type="application/pdf", content=b"%PDF-1.4 body"
            )
        ]
    )

    mime = _sent_mime(captured_send)
    assert mime.is_multipart()
    assert mime.get_content_type() == "multipart/mixed"

    parts = [p for p in mime.iter_attachments()]
    assert len(parts) == 1
    assert parts[0].get_filename() == "invoice.pdf"
    assert parts[0].get_content_type() == "application/pdf"
    assert parts[0].get_payload(decode=True) == b"%PDF-1.4 body"


def test_send_preserves_body_text_alongside_attachments(captured_send):
    _send([OutboundAttachment(attachment_id=1, filename="a.txt", mime_type="text/plain", content=b"hi")])

    mime = _sent_mime(captured_send)
    body = mime.get_body(preferencelist=("plain",))
    assert body.get_content().strip() == "Here you go."


def test_multiple_attachments_all_present_in_order(captured_send):
    _send(
        [
            OutboundAttachment(attachment_id=1, filename="one.txt", mime_type="text/plain", content=b"1"),
            OutboundAttachment(attachment_id=2, filename="two.png", mime_type="image/png", content=b"2"),
        ]
    )

    mime = _sent_mime(captured_send)
    parts = list(mime.iter_attachments())
    assert [p.get_filename() for p in parts] == ["one.txt", "two.png"]
    assert [p.get_content_type() for p in parts] == ["text/plain", "image/png"]


def test_unparseable_mime_type_falls_back_to_octet_stream(captured_send):
    _send([OutboundAttachment(attachment_id=1, filename="odd.bin", mime_type="nonsense", content=b"x")])

    mime = _sent_mime(captured_send)
    part = next(iter(mime.iter_attachments()))
    assert part.get_content_type() == "nonsense/octet-stream"


def test_send_still_targets_the_thread(captured_send):
    _send([OutboundAttachment(attachment_id=1, filename="a.txt", mime_type="text/plain", content=b"hi")])

    assert captured_send["body"]["threadId"] == "thread-1"
    assert captured_send["userId"] == "me"


def test_send_reply_sets_cc_header(captured_send):
    _send(cc_email="team@example.com")

    mime = _sent_mime(captured_send)
    assert mime["Cc"] == "team@example.com"


def test_send_forward_sets_cc_header(captured_send):
    _send(cc_email="team@example.com", forward=True)

    mime = _sent_mime(captured_send)
    assert mime["Cc"] == "team@example.com"
