import base64
from unittest.mock import MagicMock, patch

from app.services.gmail_client import list_thread_drafts


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _fake_service(draft_stubs, draft_details):
    service = MagicMock()
    service.users.return_value.drafts.return_value.list.return_value.execute.return_value = {"drafts": draft_stubs}

    def fake_get(userId, id, format):  # noqa: A002 - matches the Gmail API's kwarg names
        return MagicMock(execute=MagicMock(return_value=draft_details[id]))

    service.users.return_value.drafts.return_value.get.side_effect = fake_get
    return service


@patch("app.services.gmail_client.build")
def test_list_thread_drafts_filters_by_thread_id(mock_build):
    draft_details = {
        "draft-a": {
            "id": "draft-a",
            "message": {
                "threadId": "thread-1",
                "payload": {
                    "headers": [{"name": "Subject", "value": "Re: Booking"}],
                    "body": {"data": _encode("Draft body for thread 1")},
                },
            },
        },
        "draft-b": {
            "id": "draft-b",
            "message": {
                "threadId": "thread-2",
                "payload": {
                    "headers": [{"name": "Subject", "value": "Unrelated"}],
                    "body": {"data": _encode("Other thread draft")},
                },
            },
        },
    }
    mock_build.return_value = _fake_service([{"id": "draft-a"}, {"id": "draft-b"}], draft_details)

    results = list_thread_drafts(object(), "thread-1")

    assert len(results) == 1
    assert results[0]["draft_id"] == "draft-a"
    assert results[0]["subject"] == "Re: Booking"
    assert results[0]["body_text"] == "Draft body for thread 1"


@patch("app.services.gmail_client.build")
def test_list_thread_drafts_returns_empty_when_no_match(mock_build):
    draft_details = {
        "draft-b": {
            "id": "draft-b",
            "message": {
                "threadId": "thread-2",
                "payload": {"headers": [], "body": {"data": _encode("Other thread draft")}},
            },
        },
    }
    mock_build.return_value = _fake_service([{"id": "draft-b"}], draft_details)

    results = list_thread_drafts(object(), "thread-1")

    assert results == []
