import os
from typing import Any

from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_client: Any | None = None


class GeminiClientError(RuntimeError):
    pass


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
