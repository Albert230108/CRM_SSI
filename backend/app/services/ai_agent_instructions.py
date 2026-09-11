"""Derives an AiAgentProfile's flat `instructions` text from its canvas card representation.

Mirrors ai_reply_service._build_sections_prompt's block-joining exactly, but deliberately skips
brain/tenant placeholder resolution: `instructions` must keep `{{...}}` tokens literal so the
normal send-time resolution (see datetime_placeholders.py and the 11+ read sites of
`profile.instructions`) still runs unchanged.
"""

from __future__ import annotations

from typing import Any


def build_instructions_text(sections: list[dict[str, Any]] | None) -> str:
    ordered = sorted(sections or [], key=lambda section: section.get("order") or 0)
    blocks: list[str] = []
    for section in ordered:
        label = str(section.get("label") or "").strip()
        content = str(section.get("content") or "").strip()
        if not content:
            continue
        blocks.append(f"## {label}\n{content}" if label else content)
    return "\n\n".join(blocks)
