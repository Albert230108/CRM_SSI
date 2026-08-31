from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.device_token import DeviceToken
from app.models.user import User
from app.schemas.device_token import DeviceTokenRead, DeviceTokenRegister, DeviceTokenUnregister

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/register", response_model=DeviceTokenRead)
def register_device(
    payload: DeviceTokenRegister,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeviceToken:
    """Register (or refresh) this device's push token for the current user.

    Upserts by token: a token already on file is re-pointed at the current user (e.g. a shared
    device, or the same device after a re-login) and its last_seen_at is bumped.
    """
    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Device token is required")

    now = datetime.now(timezone.utc)
    device = db.query(DeviceToken).filter(DeviceToken.token == token).first()
    if device is None:
        device = DeviceToken(
            user_id=current_user.id, token=token, platform=payload.platform, last_seen_at=now
        )
        db.add(device)
    else:
        device.user_id = current_user.id
        if payload.platform:
            device.platform = payload.platform
        device.last_seen_at = now

    db.commit()
    db.refresh(device)
    return device


@router.post("/unregister", status_code=status.HTTP_204_NO_CONTENT)
def unregister_device(
    payload: DeviceTokenUnregister,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Remove this device's push token for the current user (called on logout)."""
    token = payload.token.strip()
    if token:
        db.query(DeviceToken).filter(
            DeviceToken.token == token, DeviceToken.user_id == current_user.id
        ).delete()
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
