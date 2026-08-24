from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.redo_request_log import RedoRequestLog


def log_redo_request(
    db: Session,
    *,
    tenant_id: int,
    channel: str,
    what: str,
    why: str | None,
    requested_by_user_id: int | None,
    ai_auto_draft_id: int | None = None,
    ai_agent_run_id: int | None = None,
) -> RedoRequestLog:
    """Exactly one of ai_auto_draft_id / ai_agent_run_id should be set - see RedoRequestLog."""
    entry = RedoRequestLog(
        ai_auto_draft_id=ai_auto_draft_id,
        ai_agent_run_id=ai_agent_run_id,
        tenant_id=tenant_id,
        channel=channel,
        what=what,
        why=why,
        requested_by_user_id=requested_by_user_id,
    )
    db.add(entry)
    db.flush()
    return entry
