from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_auto_draft import AiAutoDraft
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.ai_auto_draft import AiAutoDraftRead
from app.services import ai_auto_draft_service

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
