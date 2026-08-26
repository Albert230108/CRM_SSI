import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_MAX_OUTPUT_TOKENS_RETRY_CEILING = 8192

_client: Any | None = None

# Models occasionally wrap JSON in a markdown fence despite responseMimeType; strip it rather
# than burn a retry on a response whose content is actually correct.
_JSON_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class GeminiClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationResult:
    """One model call's output plus the metering the run log needs."""

    text: str
    parsed: dict | None
    model: str
    prompt_tokens: int | None
    output_tokens: int | None
    latency_ms: int


@dataclass(frozen=True)
class FilePart:
    """One inline file to attach to a Gemini call alongside the text prompt."""

    data: bytes
    mime_type: str


def _get_client() -> Any:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise GeminiClientError("GEMINI_API_KEY is not configured")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def generate_text_flat(prompt: str) -> str:
    """Send a single flat prompt string with no system/user split.

    Used so the payload actually sent to Gemini is byte-identical to what the
    "preview payload" feature shows the user before they click "Draft with AI".
    """
    client = _get_client()
    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    except Exception as exc:
        raise GeminiClientError(f"Gemini generation failed: {exc}") from exc

    text = (response.text or "").strip() if response is not None else ""
    if not text:
        raise GeminiClientError("Gemini returned an empty response")
    return text


def _extract_json(text: str) -> dict:
    candidate = text.strip()
    fenced = _JSON_FENCE_PATTERN.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}")
    return parsed


def generate(
    prompt: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    response_schema: dict | None = None,
    file_parts: list[FilePart] | None = None,
) -> GenerationResult:
    """Single flat-prompt call with per-call model/sampling overrides and optional JSON output.

    When `response_schema` is given the model is constrained to that JSON Schema and the parsed
    object is returned alongside the raw text. A response that still fails to parse is retried
    once - a second failure is a real error, not a blip worth hiding from the caller.
    """
    client = _get_client()
    resolved_model = model or GEMINI_MODEL

    config_kwargs: dict[str, Any] = {}
    if temperature is not None:
        config_kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = max_output_tokens
    if response_schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_json_schema"] = response_schema
    config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    contents: str | list[Any] = prompt
    if file_parts:
        contents = [prompt] + [types.Part.from_bytes(data=fp.data, mime_type=fp.mime_type) for fp in file_parts]

    last_error: Exception | None = None
    last_truncated = False
    for attempt in range(2):
        started = time.monotonic()
        try:
            response = client.models.generate_content(
                model=resolved_model, contents=contents, config=config
            )
        except Exception as exc:
            raise GeminiClientError(f"Gemini generation failed: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        text = (response.text or "").strip() if response is not None else ""
        if not text:
            raise GeminiClientError("Gemini returned an empty response")

        candidates = getattr(response, "candidates", None) or []
        finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
        truncated = finish_reason is not None and "MAX_TOKENS" in str(finish_reason)

        parsed: dict | None = None
        if response_schema is not None:
            try:
                parsed = _extract_json(text)
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                last_truncated = truncated
                current_cap = config_kwargs.get("max_output_tokens")
                if truncated:
                    logger.warning(
                        "Gemini response truncated at max_output_tokens=%s (finish_reason=MAX_TOKENS)%s",
                        current_cap,
                        "; retrying with a higher cap" if attempt == 0 and current_cap else " on retry",
                    )
                if attempt == 0:
                    if truncated and current_cap:
                        new_cap = min(current_cap * 2, _MAX_OUTPUT_TOKENS_RETRY_CEILING)
                        config_kwargs["max_output_tokens"] = new_cap
                        config = types.GenerateContentConfig(**config_kwargs)
                    continue
                if last_truncated:
                    raise GeminiClientError(
                        f"Gemini response was truncated (max_output_tokens too low) and could not "
                        f"be parsed as JSON: {exc}"
                    ) from exc
                raise GeminiClientError(f"Gemini returned unparseable JSON: {exc}") from exc
        if truncated:
            last_truncated = True
            current_cap = config_kwargs.get("max_output_tokens")
            logger.warning(
                "Gemini response truncated at max_output_tokens=%s (finish_reason=MAX_TOKENS)%s",
                current_cap,
                "; retrying with a higher cap" if attempt == 0 and current_cap else " on retry",
            )
            if attempt == 0:
                if current_cap:
                    new_cap = min(current_cap * 2, _MAX_OUTPUT_TOKENS_RETRY_CEILING)
                    config_kwargs["max_output_tokens"] = new_cap
                    config = types.GenerateContentConfig(**config_kwargs)
                continue
            raise GeminiClientError(
                "Gemini response was truncated (max_output_tokens too low) and could not be "
                "returned successfully after retry"
            )

        usage = getattr(response, "usage_metadata", None)
        return GenerationResult(
            text=text,
            parsed=parsed,
            model=resolved_model,
            prompt_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            output_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
            latency_ms=latency_ms,
        )

    if last_truncated:
        raise GeminiClientError(
            f"Gemini response was truncated (max_output_tokens too low) and could not be "
            f"parsed as JSON: {last_error}"
        )
    raise GeminiClientError(f"Gemini returned unparseable JSON: {last_error}")
