from datetime import timedelta, timezone, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.security import create_access_token, verify_password, generate_secure_token, hash_token, get_password_hash
from app.models.invitation import Invitation
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.schemas.auth import CurrentUser, LoginRequest, Token
from app.schemas.user import InvitationComplete, PasswordResetComplete

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    access_token = create_access_token({"sub": str(user.id)})
    return Token(access_token=access_token)


@router.get("/me", response_model=CurrentUser)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/invitations/{token}/complete", response_model=Token)
def complete_invitation(token: str, payload: InvitationComplete, db: Session = Depends(get_db)) -> Token:
    token_hash = hash_token(token)
    invitation = db.query(Invitation).filter(Invitation.token_hash == token_hash).first()
    if invitation is None or invitation.used_at is not None or invitation.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invitation")
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")

    user = db.query(User).filter(User.email == invitation.email).first()
    if user is None:
        user = User(email=invitation.email, full_name=payload.full_name or invitation.full_name, password_hash=generate_secure_token(), is_active=True, is_admin=invitation.is_admin)
        db.add(user)
        db.flush()
    else:
        user.full_name = payload.full_name or user.full_name or invitation.full_name
        user.is_active = True
        user.is_admin = user.is_admin or invitation.is_admin
    user.password_hash = get_password_hash(payload.password)
    invitation.used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return Token(access_token=create_access_token({"sub": str(user.id)}))


@router.post("/password-reset/{token}/complete", response_model=Token)
def complete_password_reset(token: str, payload: PasswordResetComplete, db: Session = Depends(get_db)) -> Token:
    token_hash = hash_token(token)
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()
    if reset_token is None or reset_token.used_at is not None or reset_token.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = get_password_hash(payload.password)
    reset_token.used_at = datetime.now(timezone.utc)
    db.commit()
    return Token(access_token=create_access_token({"sub": str(user.id)}))
