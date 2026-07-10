from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user, get_db
from app.core.security import generate_secure_token, get_password_hash, hash_token
from app.core.public_urls import get_public_frontend_base_url
from app.models.invitation import Invitation
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.schemas.user import InviteCreate, InviteRead, PasswordResetRequestCreate, UserRead, UserUpdate
from app.services.email_service import send_email

router = APIRouter(prefix="/users", tags=["users"])
INVITATION_HOURS = 72
RESET_HOURS = 24


def _public_base_url() -> str:
    return get_public_frontend_base_url()


@router.get("", response_model=list[UserRead], dependencies=[Depends(get_current_admin_user)])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return db.query(User).order_by(User.id).all()


@router.put("/{user_id}", response_model=UserRead, dependencies=[Depends(get_current_admin_user)])
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.is_active is False and user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")
    if payload.is_admin is False and user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot remove your own admin access")

    if payload.email is not None:
        existing = db.query(User).filter(User.email == payload.email, User.id != user.id).first()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        user.email = payload.email
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.phone is not None:
        user.phone = payload.phone
    if payload.password is not None:
        user.password_hash = get_password_hash(payload.password)
    if payload.is_active is not None:
        if payload.is_active is False and user.is_admin:
            active_admins = db.query(User).filter(User.is_admin.is_(True), User.is_active.is_(True), User.id != user.id).count()
            if active_admins == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one active admin must remain")
        user.is_active = payload.is_active
    if payload.is_admin is not None:
        if payload.is_admin is False and user.is_admin:
            active_admins = db.query(User).filter(User.is_admin.is_(True), User.is_active.is_(True), User.id != user.id).count()
            if active_admins == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one active admin must remain")
        user.is_admin = payload.is_admin

    db.commit()
    db.refresh(user)
    return user


@router.post("/invite", response_model=InviteRead, dependencies=[Depends(get_current_admin_user)])
def create_invite(payload: InviteCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> InviteRead:
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user is not None and existing_user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")

    raw_token = generate_secure_token()
    invitation = Invitation(
        email=payload.email,
        full_name=payload.full_name,
        is_admin=payload.is_admin,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=INVITATION_HOURS),
        created_by_id=current_user.id,
    )
    db.add(invitation)
    db.commit()
    invite_url = f"{_public_base_url()}/invite/{raw_token}"
    send_email(payload.email, "Your CRM invitation", f"You have been invited to CRM SSI. Complete setup here: {invite_url}")
    return InviteRead(token=raw_token, invite_url=invite_url)


@router.post("/{user_id}/password-reset", dependencies=[Depends(get_current_admin_user)])
def create_password_reset(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> dict[str, str]:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    raw_token = generate_secure_token()
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=RESET_HOURS),
        created_by_id=current_user.id,
    )
    db.add(reset_token)
    db.commit()
    reset_url = f"{_public_base_url()}/reset-password/{raw_token}"
    send_email(user.email, "Password reset request", f"Reset your CRM password here: {reset_url}")
    return {"reset_url": reset_url}


@router.post("/{user_id}/toggle-active", response_model=UserRead, dependencies=[Depends(get_current_admin_user)])
def toggle_user_active(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_user.id and user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")
    if user.is_active and user.is_admin:
        active_admins = db.query(User).filter(User.is_admin.is_(True), User.is_active.is_(True), User.id != user.id).count()
        if active_admins == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one active admin must remain")
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    return user