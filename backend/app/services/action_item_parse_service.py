"""Parses a single quick-add text line (e.g. "Call guest tomorrow 5pm") into a structured
action-item draft for the user to confirm. A single fixed micro-prompt, not a configurable
agent - no AiAgentProfile, toggle, or debounce, just a synchronous request/response.
"""
from __future__ import annotations

from datetime import date

from app.services import gemini_client

_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "due_date": {"type": "string"},
        "priority": {"type": "string"},
    },
    "required": ["title"],
}

_VALID_PRIORITIES = {"p1", "p2", "p3", "p4"}


def parse_quick_add(text: str) -> dict | None:
    today = date.today().isoformat()
    prompt = (
        "Extract a task title and, if present, a due date and priority from this quick-add "
        "text for a short-stay rental CRM's action-item list.\n"
        f"Today's date is {today}. Resolve relative dates (e.g. 'tomorrow', 'next Friday') "
        "against it and return due_date as YYYY-MM-DD, omitted if no date is implied.\n"
        "priority is one of p1 (most urgent) to p4 (least urgent) - only set it if the text "
        "clearly implies urgency, otherwise omit it.\n"
        "Strip the date/time/priority phrase out of the returned title so it reads as a clean "
        "task description.\n\n"
        f'Text: "{text}"'
    )
    try:
        result = gemini_client.generate(prompt, response_schema=_SCHEMA)
    except gemini_client.GeminiClientError:
        return None

    parsed = result.parsed or {}
    title = str(parsed.get("title") or "").strip()
    if not title:
        return None

    due_date = None
    due_date_raw = str(parsed.get("due_date") or "").strip()
    if due_date_raw:
        try:
            due_date = date.fromisoformat(due_date_raw)
        except ValueError:
            due_date = None

    priority = str(parsed.get("priority") or "").strip().lower() or None
    if priority not in _VALID_PRIORITIES:
        priority = None

    return {"title": title, "due_date": due_date, "priority": priority}
