import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import gemini_client


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    monkeypatch.setattr(gemini_client, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_client, "_client", None)


def _response(text: str, finish_reason: str | None) -> SimpleNamespace:
    candidate = SimpleNamespace(finish_reason=finish_reason)
    return SimpleNamespace(text=text, candidates=[candidate], usage_metadata=None)


def _install_fake_client(monkeypatch, generate_content: Mock) -> None:
    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake_client)


SCHEMA = {"type": "object", "properties": {"passed": {"type": "boolean"}}}


def test_truncated_response_retries_with_bumped_cap_and_succeeds(monkeypatch, caplog):
    truncated_text = '{"passed": true, "feedback": "unterminated'
    complete_text = '{"passed": true, "feedback": "ok"}'
    generate_content = Mock(
        side_effect=[
            _response(truncated_text, "MAX_TOKENS"),
            _response(complete_text, "STOP"),
        ]
    )
    _install_fake_client(monkeypatch, generate_content)

    with caplog.at_level(logging.WARNING):
        result = gemini_client.generate(
            "prompt", max_output_tokens=1024, response_schema=SCHEMA
        )

    assert result.parsed == {"passed": True, "feedback": "ok"}
    assert "truncated" in caplog.text.lower()

    first_call_cap = generate_content.call_args_list[0].kwargs["config"].max_output_tokens
    second_call_cap = generate_content.call_args_list[1].kwargs["config"].max_output_tokens
    assert first_call_cap == 1024
    assert second_call_cap > first_call_cap


def test_truncated_on_both_attempts_raises_truncation_specific_error(monkeypatch):
    truncated_text = '{"passed": true, "feedback": "unterminated'
    generate_content = Mock(
        side_effect=[
            _response(truncated_text, "MAX_TOKENS"),
            _response(truncated_text, "MAX_TOKENS"),
        ]
    )
    _install_fake_client(monkeypatch, generate_content)

    with pytest.raises(gemini_client.GeminiClientError) as exc_info:
        gemini_client.generate("prompt", max_output_tokens=1024, response_schema=SCHEMA)

    assert "truncated" in str(exc_info.value).lower()


def test_generic_malformed_json_retries_identically_and_raises_generic_error(monkeypatch):
    malformed_text = "not json at all"
    generate_content = Mock(
        side_effect=[
            _response(malformed_text, "STOP"),
            _response(malformed_text, "STOP"),
        ]
    )
    _install_fake_client(monkeypatch, generate_content)

    with pytest.raises(gemini_client.GeminiClientError) as exc_info:
        gemini_client.generate("prompt", max_output_tokens=1024, response_schema=SCHEMA)

    assert "unparseable json" in str(exc_info.value).lower()
    assert "truncated" not in str(exc_info.value).lower()

    first_call_cap = generate_content.call_args_list[0].kwargs["config"].max_output_tokens
    second_call_cap = generate_content.call_args_list[1].kwargs["config"].max_output_tokens
    assert first_call_cap == second_call_cap == 1024


def test_truncated_free_text_retries_without_cap_and_raises_on_second_failure(monkeypatch):
    truncated_text = "This draft was cut off mid sentence"
    generate_content = Mock(
        side_effect=[
            _response(truncated_text, "MAX_TOKENS"),
            _response(truncated_text, "MAX_TOKENS"),
        ]
    )
    _install_fake_client(monkeypatch, generate_content)

    with pytest.raises(gemini_client.GeminiClientError) as exc_info:
        gemini_client.generate("prompt")

    assert "truncated" in str(exc_info.value).lower()
    assert len(generate_content.call_args_list) == 2
    assert generate_content.call_args_list[0].kwargs.get("config") is None
    assert generate_content.call_args_list[1].kwargs.get("config") is None
