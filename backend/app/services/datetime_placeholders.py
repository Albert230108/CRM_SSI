from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _now() -> datetime:
    return datetime.now().astimezone()


DATETIME_PLACEHOLDER_FIELDS: dict[str, Callable[[], str]] = {
    "current_date": lambda: _now().date().isoformat(),
    "current_time": lambda: _now().time().isoformat(timespec="seconds"),
    "current_datetime": lambda: _now().isoformat(timespec="seconds"),
}


def resolve_datetime_placeholders(text: str) -> str:
    """Replace datetime placeholders and leave unknown tokens untouched."""

    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        getter = DATETIME_PLACEHOLDER_FIELDS.get(match.group(1))
        return getter() if getter is not None else match.group(0)

    return _PLACEHOLDER_PATTERN.sub(_replace, text)
