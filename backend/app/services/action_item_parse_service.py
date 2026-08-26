"""Parses a single quick-add text line (e.g. "Call guest tomorrow 5pm") into a structured
action-item draft for the user to confirm. A single fixed micro-prompt, not a configurable
agent - no AiAgentProfile, toggle, or debounce, just a synchronous request/response.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.services import action_tag_service, gemini_client

_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "due_date": {"type": "string"},
        "priority": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title"],
}

_VALID_PRIORITIES = {"p1", "p2", "p3", "p4"}


def parse_quick_add(text: str, db: Session) -> dict | None:
    today = date.today().isoformat()
    active_tags = action_tag_service.list_definitions(db, active_only=True)
    prompt_parts = [
        "Extract a task title and, if present, a due date, priority, and tags from this quick-add text for a short-stay rental CRM's action-item list.",
        f"Today's date is {today}. Resolve relative dates (e.g. 'tomorrow', 'next Friday') against it and return due_date as YYYY-MM-DD, omitted if no date is implied.",
        "priority is one of p1 (most urgent) to p4 (least urgent) - only set it if the text clearly implies urgency, otherwise omit it.",
        "Strip the date/time/priority phrase out of the returned title so it reads as a clean task description.",
    ]
    if active_tags:
        prompt_parts.append("tags must be zero or more exact names from the available tag list below, omitted if none clearly apply:")
        prompt_parts.extend(f"- {tag.name}" for tag in active_tags)
    prompt_parts.append(f'Text: "{text}"')
    prompt = "\n".join(prompt_parts)
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

    tag_ids = action_tag_service.resolve_tag_ids(db, parsed.get("tags"))

    return {"title": title, "due_date": due_date, "priority": priority, "tag_ids": tag_ids}
