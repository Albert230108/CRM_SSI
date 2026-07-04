from __future__ import annotations

import re

_DIGIT_RE = re.compile(r"\d+")
_WHATSAPP_ID_RE = re.compile(r"^wa_id[:=]\s*", re.IGNORECASE)


def normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(_DIGIT_RE.findall(value))
    return digits or None


def phone_match_candidates(value: str | None) -> list[str]:
    if not value:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str | None) -> None:
        normalized = normalize_phone(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    raw = value.strip()
    add(raw)
    add(_WHATSAPP_ID_RE.sub("", raw))

    if "@" in raw:
        add(raw.split("@", 1)[0])

    if raw.startswith("+"):
        add(raw.lstrip("+"))

    if raw.startswith("00"):
        add(raw[2:])

    if any(separator in raw for separator in (" ", "-", "(", ")", ".", "/")):
        add(re.sub(r"[^\d]", "", raw))

    return candidates
