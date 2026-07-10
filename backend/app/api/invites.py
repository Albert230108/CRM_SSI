from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.security import create_access_token, generate_secure_token, get_password_hash, hash_token
from app.models.admin_invite import AdminInvite
from app.models.user import User
from app.schemas.user import InvitationComplete

router = APIRouter(prefix="/invites", tags=["invites"])


def _invite_status(invite: AdminInvite) -> bool:
    now = datetime.now(timezone.utc)
    if invite.used_at is not None or invite.revoked_at is not None:
        return False
    return invite.expires_at > now


@router.get("/{token}")
def get_invite(token: str, db: Session = Depends(get_db)) -> dict[str, str | int | None]:
    invite = db.query(AdminInvite).filter(AdminInvite.token_hash == hash_token(token)).first()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    now = datetime.now(timezone.utc)
    if invite.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invite has been revoked")
    if invite.used_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invite has already been completed")
    if invite.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invite has expired")
    return {
        "email": invite.email,
        "full_name": invite.full_name,
        "phone": invite.phone,
        "role": invite.role,
        "expires_at": invite.expires_at.isoformat(),
    }


@router.post("/{token}/complete")
def complete_invite(token: str, payload: InvitationComplete, db: Session = Depends(get_db)) -> dict[str, str]:
    invite = db.query(AdminInvite).filter(AdminInvite.token_hash == hash_token(token)).first()
    if invite is None or not _invite_status(invite):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invitation")
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")

    first_name = (payload.first_name or "").strip()
    last_name = (payload.last_name or "").strip()
    resolved_name = " ".join(part for part in [first_name, last_name] if part).strip() or invite.full_name
    resolved_email = (payload.email or invite.email or "").strip()
    if not resolved_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required")
    if invite.email and resolved_email.lower() != invite.email.lower():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email does not match the invite")

    user = db.query(User).filter(User.email == resolved_email).first()
    password_hash = get_password_hash(payload.password)
    if user is None:
        user = User(
            email=resolved_email,
            full_name=resolved_name,
            phone=(payload.phone or invite.phone),
            password_hash=password_hash,
            is_active=True,
            is_admin=invite.role == "admin",
        )
        db.add(user)
        db.flush()
    else:
        user.full_name = resolved_name or user.full_name
        user.phone = (payload.phone or invite.phone or user.phone)
        user.is_active = True
        user.is_admin = user.is_admin or invite.role == "admin"
        user.password_hash = password_hash

    invite.used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    db.refresh(invite)
    return {"access_token": create_access_token({"sub": str(user.id)})}