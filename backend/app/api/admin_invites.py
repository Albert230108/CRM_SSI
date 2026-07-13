from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user, get_db
from app.core.security import generate_secure_token, hash_token
from app.core.public_urls import get_public_frontend_base_url
from app.models.admin_invite import AdminInvite
from app.models.user import User
from app.schemas.user import AdminInviteClearResult, AdminInviteCreate, AdminInviteRead
from app.services.email_service import send_email

router = APIRouter(prefix="/admin/invites", tags=["admin-invites"])
INVITATION_HOURS = 72


def _public_base_url() -> str:
    return get_public_frontend_base_url()


def _as_aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _invite_status(invite: AdminInvite) -> str:
    now = datetime.now(timezone.utc)
    if invite.revoked_at is not None:
        return "revoked"
    if invite.used_at is not None:
        return "completed"
    if _as_aware_utc(invite.expires_at) <= now:
        return "expired"
    return "pending"


def _to_read(invite: AdminInvite, token: str | None = None) -> AdminInviteRead:
    invite_url = f"{_public_base_url()}/invite/{token}" if token else None
    return AdminInviteRead(
        id=invite.id,
        email=invite.email,
        full_name=invite.full_name,
        phone=invite.phone,
        role=invite.role,
        status=_invite_status(invite),
        invite_url=invite_url,
        expires_at=invite.expires_at,
        used_at=invite.used_at,
        revoked_at=invite.revoked_at,
        created_at=invite.created_at,
        updated_at=invite.updated_at,
        invited_by_user_id=invite.invited_by_user_id,
    )


@router.get("", response_model=list[AdminInviteRead], dependencies=[Depends(get_current_admin_user)])
def list_invites(db: Session = Depends(get_db)) -> list[AdminInviteRead]:
    invites = db.query(AdminInvite).order_by(AdminInvite.created_at.desc(), AdminInvite.id.desc()).all()
    return [_to_read(invite) for invite in invites]


@router.post("", response_model=AdminInviteRead, dependencies=[Depends(get_current_admin_user)])
def create_invite(payload: AdminInviteCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> AdminInviteRead:
    if payload.email:
        existing_user = db.query(User).filter(User.email == payload.email).first()
        if existing_user is not None and existing_user.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")

    raw_token = generate_secure_token()
    invite = AdminInvite(
        email=payload.email,
        full_name=payload.full_name,
        phone=payload.phone,
        role=payload.role,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=INVITATION_HOURS),
        invited_by_user_id=current_user.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    invite_url = f"{_public_base_url()}/invite/{raw_token}"
    if payload.email:
        send_email(payload.email, "Your CRM SSI invite", f"You have been invited to CRM SSI. Complete setup here: {invite_url}")
    return _to_read(invite, raw_token)


@router.post("/clear", response_model=AdminInviteClearResult, dependencies=[Depends(get_current_admin_user)])
def clear_pending_invites(db: Session = Depends(get_db)) -> AdminInviteClearResult:
    now = datetime.now(timezone.utc)
    pending_invites = db.query(AdminInvite).filter(AdminInvite.revoked_at.is_(None)).all()

    revoked_count = 0
    skipped_accepted_count = 0
    skipped_expired_count = 0
    for invite in pending_invites:
        if invite.used_at is not None:
            skipped_accepted_count += 1
            continue
        if _as_aware_utc(invite.expires_at) <= now:
            skipped_expired_count += 1
            continue
        invite.revoked_at = now
        revoked_count += 1

    db.commit()
    return AdminInviteClearResult(
        revoked_count=revoked_count,
        skipped_accepted_count=skipped_accepted_count,
        skipped_expired_count=skipped_expired_count,
    )


@router.post("/{invite_id}/revoke", response_model=AdminInviteRead, dependencies=[Depends(get_current_admin_user)])
def revoke_invite(invite_id: int, db: Session = Depends(get_db)) -> AdminInviteRead:
    invite = db.query(AdminInvite).filter(AdminInvite.id == invite_id).first()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if invite.used_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite already completed")
    invite.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(invite)
    return _to_read(invite)


@router.post("/{invite_id}/regenerate", response_model=AdminInviteRead, dependencies=[Depends(get_current_admin_user)])
def regenerate_invite(invite_id: int, db: Session = Depends(get_db)) -> AdminInviteRead:
    invite = db.query(AdminInvite).filter(AdminInvite.id == invite_id).first()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if invite.used_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite already completed")
    raw_token = generate_secure_token()
    invite.token_hash = hash_token(raw_token)
    invite.expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITATION_HOURS)
    invite.revoked_at = None
    db.commit()
    db.refresh(invite)
    return _to_read(invite, raw_token)