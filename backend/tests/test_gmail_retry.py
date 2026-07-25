from googleapiclient.errors import HttpError

from app.api.gmail_integration import _execute_gmail_request


class _FakeResp(dict):
    """Dict subclass so exc.resp.get('retry-after') works, matching httplib2.Response."""

    def __init__(self, status, headers=None):
        super().__init__(headers or {})
        self.status = status
        self.reason = "Error"


class _FakeRequest:
    def __init__(self, effects):
        self._effects = list(effects)
        self.call_count = 0

    def execute(self):
        self.call_count += 1
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


def _rate_limited(status=429, headers=None, message="Rate Limit Exceeded"):
    body = ('{"error": {"message": "%s"}}' % message).encode("utf-8")
    return HttpError(_FakeResp(status, headers), body)


def test_retries_429_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.api.gmail_integration.time.sleep", lambda s: sleeps.append(s))

    request = _FakeRequest([_rate_limited(429), {"ok": 1}])

    result = _execute_gmail_request(request)

    assert result == {"ok": 1}
    assert request.call_count == 2
    assert sleeps == [1.0]


def test_honors_retry_after_header(monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.api.gmail_integration.time.sleep", lambda s: sleeps.append(s))

    request = _FakeRequest([_rate_limited(429, headers={"retry-after": "3"}), {"ok": 1}])

    result = _execute_gmail_request(request)

    assert result == {"ok": 1}
    assert sleeps == [3.0]


def test_exhausts_retries_and_raises(monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.api.gmail_integration.time.sleep", lambda s: sleeps.append(s))

    request = _FakeRequest([_rate_limited(429), _rate_limited(429), _rate_limited(429)])

    try:
        _execute_gmail_request(request, max_retries=2)
        assert False, "expected HttpError to propagate"
    except HttpError as exc:
        assert exc.resp.status == 429

    assert request.call_count == 3
    assert len(sleeps) == 2


def test_does_not_retry_non_429_errors(monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.api.gmail_integration.time.sleep", lambda s: sleeps.append(s))

    not_found = HttpError(_FakeResp(404), b'{"error": {"message": "Not Found"}}')
    request = _FakeRequest([not_found])

    try:
        _execute_gmail_request(request)
        assert False, "expected HttpError to propagate"
    except HttpError as exc:
        assert exc.resp.status == 404

    assert request.call_count == 1
    assert sleeps == []


def test_retries_403_with_rate_limit_reason(monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.api.gmail_integration.time.sleep", lambda s: sleeps.append(s))

    request = _FakeRequest(
        [_rate_limited(403, message="User Rate Limit Exceeded"), {"ok": 1}]
    )

    result = _execute_gmail_request(request)

    assert result == {"ok": 1}
    assert request.call_count == 2


def test_does_not_retry_generic_403(monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.api.gmail_integration.time.sleep", lambda s: sleeps.append(s))

    forbidden = HttpError(
        _FakeResp(403), b'{"error": {"message": "The caller does not have permission"}}'
    )
    request = _FakeRequest([forbidden])

    try:
        _execute_gmail_request(request)
        assert False, "expected HttpError to propagate"
    except HttpError as exc:
        assert exc.resp.status == 403

    assert request.call_count == 1
    assert sleeps == []
