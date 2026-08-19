from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user, get_current_user, get_db
from app.core.security import generate_secure_token, get_password_hash, hash_token
from app.core.public_urls import get_public_frontend_base_url
from app.models.admin_invite import AdminInvite
from app.models.password_reset import PasswordResetToken
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User
from app.schemas.user import (
    AdminUserCreate,
    PinnedTenantsRead,
    PinnedTenantsUpdate,
    TenantStatusFilterRead,
    TenantStatusFilterUpdate,
    UserDeleteResult,
    UserRead,
    UserUpdate,
)
from app.services.email_service import send_email

router = APIRouter(prefix="/users", tags=["users"])
RESET_HOURS = 24


def _public_base_url() -> str:
    return get_public_frontend_base_url()


@router.get("/me/tenant-status-filter", response_model=TenantStatusFilterRead)
def get_tenant_status_filter(current_user: User = Depends(get_current_user)) -> TenantStatusFilterRead:
    return TenantStatusFilterRead(statuses=current_user.tenant_status_filter)


@router.put("/me/tenant-status-filter", response_model=TenantStatusFilterRead)
def update_tenant_status_filter(
    payload: TenantStatusFilterUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantStatusFilterRead:
    current_user.tenant_status_filter = payload.statuses
    db.commit()
    db.refresh(current_user)
    return TenantStatusFilterRead(statuses=current_user.tenant_status_filter)


@router.get("/me/pinned-tenants", response_model=PinnedTenantsRead)
def get_pinned_tenants(current_user: User = Depends(get_current_user)) -> PinnedTenantsRead:
    return PinnedTenantsRead(tenant_ids=current_user.pinned_tenant_ids)


@router.put("/me/pinned-tenants", response_model=PinnedTenantsRead)
def update_pinned_tenants(
    payload: PinnedTenantsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PinnedTenantsRead:
    current_user.pinned_tenant_ids = payload.tenant_ids
    db.commit()
    return PinnedTenantsRead(tenant_ids=current_user.pinned_tenant_ids)


@router.get("", response_model=list[UserRead], dependencies=[Depends(get_current_admin_user)])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(get_current_admin_user)])
def create_user(payload: AdminUserCreate, db: Session = Depends(get_db)) -> User:
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        phone=payload.phone,
        password_hash=get_password_hash(payload.password),
        is_active=True,
        is_admin=payload.is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


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


@router.post("/{user_id}/toggle-whatsapp-notifications", response_model=UserRead, dependencies=[Depends(get_current_admin_user)])
def toggle_user_whatsapp_notifications(user_id: int, db: Session = Depends(get_db)) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.whatsapp_notifications_enabled = not user.whatsapp_notifications_enabled
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=UserDeleteResult, dependencies=[Depends(get_current_admin_user)])
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> UserDeleteResult:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account")

    if user.is_active and user.is_admin:
        active_admins = db.query(User).filter(User.is_admin.is_(True), User.is_active.is_(True), User.id != user.id).count()
        if active_admins == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one active admin must remain")

    # These records only capture the deleted user's own invite/reset activity, so they are
    # removed along with the account rather than left dangling on a non-nullable FK.
    db.query(PasswordResetToken).filter(
        (PasswordResetToken.user_id == user.id) | (PasswordResetToken.created_by_id == user.id)
    ).delete(synchronize_session=False)
    db.query(AdminInvite).filter(AdminInvite.invited_by_user_id == user.id).delete(synchronize_session=False)

    # Tenant channel endpoint audit fields are nullable, so preserve the endpoint history
    # and just clear the reference to the deleted user.
    db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.linked_by_user_id == user.id).update(
        {TenantChannelEndpoint.linked_by_user_id: None}, synchronize_session=False
    )
    db.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.unlinked_by_user_id == user.id).update(
        {TenantChannelEndpoint.unlinked_by_user_id: None}, synchronize_session=False
    )

    db.delete(user)
    db.commit()
    return UserDeleteResult(id=user_id, deleted=True)