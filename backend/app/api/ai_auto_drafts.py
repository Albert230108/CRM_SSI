import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_auto_draft import AiAutoDraft
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.ai_auto_draft import AiAutoDraftRead
from app.services import ai_auto_draft_service, memory_redo_service, redo_request_log_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-auto-drafts", tags=["ai-auto-drafts"])

# "needs_review" drafts came out of the planner loop without the checker ever approving them.
# They are surfaced alongside ordinary pending drafts precisely because they need a human.
DEFAULT_STATUSES = ("pending", "pending_auto_send", "needs_review")


def _get_draft(db: Session, draft_id: int) -> AiAutoDraft:
    draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).first()
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI draft not found")
    return draft


def _to_read(db: Session, draft: AiAutoDraft) -> AiAutoDraftRead:
    tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
    return AiAutoDraftRead(
        id=draft.id,
        tenant_id=draft.tenant_id,
        tenant_name=tenant.name if tenant is not None else None,
        channel=draft.channel,
        template_id=draft.template_id,
        generated_text=draft.generated_text,
        quoted_context=draft.quoted_context,
        status=draft.status,
        scheduled_send_at=draft.scheduled_send_at,
        created_at=draft.created_at,
    )


@router.get("", response_model=list[AiAutoDraftRead])
def list_ai_auto_drafts(
    tenant_id: int | None = None,
    channel: str | None = None,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AiAutoDraftRead]:
    query = db.query(AiAutoDraft)
    if tenant_id is not None:
        query = query.filter(AiAutoDraft.tenant_id == tenant_id)
    if channel is not None:
        query = query.filter(AiAutoDraft.channel == channel)
    if status_filter is not None:
        query = query.filter(AiAutoDraft.status == status_filter)
    else:
        query = query.filter(AiAutoDraft.status.in_(DEFAULT_STATUSES))
    drafts = query.order_by(AiAutoDraft.created_at.desc(), AiAutoDraft.id.desc()).all()
    return [_to_read(db, draft) for draft in drafts]


@router.put("/{draft_id}/dismiss", response_model=AiAutoDraftRead)
def dismiss_ai_auto_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAutoDraftRead:
    draft = _get_draft(db, draft_id)
    draft.status = "dismissed"
    draft.scheduled_send_at = None
    db.commit()
    db.refresh(draft)
    return _to_read(db, draft)


@router.put("/{draft_id}/cancel-auto-send", response_model=AiAutoDraftRead)
def cancel_ai_auto_draft_send(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAutoDraftRead:
    """Downgrades a scheduled auto-send back to a plain pending draft (text kept, not sent)."""
    draft = _get_draft(db, draft_id)
    if draft.status == "pending_auto_send":
        draft.status = "pending"
        draft.scheduled_send_at = None
        db.commit()
        db.refresh(draft)
    return _to_read(db, draft)


@router.put("/{draft_id}/mark-used", response_model=AiAutoDraftRead)
def mark_ai_auto_draft_used(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAutoDraftRead:
    draft = _get_draft(db, draft_id)
    draft.status = "used_as_manual_seed"
    draft.scheduled_send_at = None
    db.commit()
    db.refresh(draft)
    return _to_read(db, draft)


class AiAutoDraftRedoRequest(BaseModel):
    what: str
    why: Optional[str] = None


@router.put("/{draft_id}/redo", response_model=AiAutoDraftRead)
def redo_ai_auto_draft(
    draft_id: int,
    payload: AiAutoDraftRedoRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAutoDraftRead:
    """The CRM counterpart to the WhatsApp "REDO-{id} what: ... why: ..." staff reply - same
    underlying regenerate_draft_via_planner call, reached from the thread view instead."""
    draft = _get_draft(db, draft_id)
    what = payload.what.strip()
    if not what:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="what is required")
    why = (payload.why or "").strip() or None
    instructions = f"What: {what}" + (f"\nWhy: {why}" if why else "")

    regenerated = ai_auto_draft_service.regenerate_draft_via_planner(db, draft, instructions)
    if regenerated is None:
        redo_request_log_service.log_redo_request(
            db, ai_auto_draft_id=draft_id, tenant_id=draft.tenant_id, channel="crm", what=what, why=why, requested_by_user_id=current_user.id
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Redo failed - planner produced no draft")

    log_entry = redo_request_log_service.log_redo_request(
        db, ai_auto_draft_id=draft_id, tenant_id=regenerated.tenant_id, channel="crm", what=what, why=why, requested_by_user_id=current_user.id
    )
    db.commit()
    db.refresh(regenerated)
    try:
        memory_redo_service.propose_updates_from_redo(db, regenerated, what, why, redo_log_id=log_entry.id)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Memory redo suggestion generation failed draft_id=%s", draft_id)
    return _to_read(db, regenerated)


@router.put("/{draft_id}/send-now", response_model=AiAutoDraftRead)
def send_ai_auto_draft_now(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAutoDraftRead:
    draft = _get_draft(db, draft_id)
    if draft.status not in DEFAULT_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft is not in a sendable state")
    sent = ai_auto_draft_service.send_scheduled_draft(db, draft)
    if not sent:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to send draft")
    db.commit()
    db.refresh(draft)
    return _to_read(db, draft)
