from __future__ import annotations

from datetime import date

from app.models.action_item import ActionItem
from app.models.memory_suggestion import MemorySuggestion


def resolve_command(text: str) -> str | None:
    normalized = " ".join((text or "").strip().lower().split())
    if normalized in {"actions", "actions today"}:
        return "today"
    if normalized == "actions upcoming":
        return "upcoming"
    if normalized == "actions pending":
        return "pending"
    if normalized == "help":
        return "help"
    return None


def _format_date(value: date | None) -> str:
    return value.isoformat() if value is not None else "no date"


def _shorten(text: str | None, limit: int = 120) -> str:
    cleaned = " ".join((text or "").strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def format_open_actions_message(items: list[ActionItem], *, tenant_names: dict[int, str], heading: str) -> str:
    lines = [heading]
    if not items:
        lines.append("No open action items found.")
        return "\n".join(lines)

    shown = items[:30]
    for item in shown:
        tenant_name = tenant_names.get(item.tenant_id, "Unknown tenant")
        lines.append(f"- {item.title} (due: {_format_date(item.due_date)}, {tenant_name})")

    remaining = len(items) - len(shown)
    if remaining > 0:
        lines.append(f"...and {remaining} more")
    return "\n".join(lines)


def _format_suggestion_value(value) -> str:
    if value is None:
        return "no date"
    return str(value)


def format_pending_suggestions_message(rows: list[tuple[MemorySuggestion, ActionItem | None, str]]) -> str:
    lines = ["📝 Pending action-item suggestions"]
    if not rows:
        lines.append("No pending action-item suggestions right now.")
        return "\n".join(lines)

    for suggestion, item, tenant_name in rows:
        lines.append(f"#{suggestion.id} {suggestion.kind.replace('_', ' ')} ({tenant_name})")
        if item is None:
            lines.append("- target: no longer exists")
        else:
            proposed = suggestion.proposed_value or {}
            current_title = item.title
            proposed_title = proposed.get("title", current_title)
            if proposed_title != current_title:
                lines.append(f"- title: {current_title} -> {proposed_title}")

            current_due = item.due_date.isoformat() if item.due_date is not None else "no date"
            proposed_due = _format_suggestion_value(proposed.get("due_date"))
            if proposed_due != current_due:
                lines.append(f"- due: {current_due} -> {proposed_due}")

            current_description = _shorten(item.description)
            proposed_description = _shorten(proposed.get("description"))
            if proposed_description != current_description:
                lines.append(f"- description: {current_description or 'no description'} -> {proposed_description or 'no description'}")

        lines.append(f"Reply YES-{suggestion.id} to approve")
        lines.append(f"Reply NO-{suggestion.id} to reject")
        lines.append("")

    return "\n".join(lines).rstrip()


def format_help_message() -> str:
    return (
        "WhatsApp staff commands\n\n"
        "AI draft approvals:\n"
        "- YES-{id} to send\n"
        "- NO-{id} to dismiss\n"
        "- REDO-{id} <what to change> to regenerate\n"
        "- bare yes/no only when exactly one draft is outstanding\n\n"
        "Action items:\n"
        "- actions or actions today: open items due today or overdue\n"
        "- actions upcoming: open items due in the next 7 days\n"
        "- actions pending: AI-proposed action-item edits/deletes awaiting approval\n"
        "- YES-{id} / NO-{id} to approve or reject a pending action-item suggestion\n\n"
        "help: show this message again"
    )
