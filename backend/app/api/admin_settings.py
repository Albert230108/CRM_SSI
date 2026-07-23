from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user, get_current_user, get_db
from app.models.admin_settings import AdminSettings
from app.schemas.admin_settings import AdminSettingsRead, AdminSettingsUpdate

router = APIRouter(prefix="/admin-settings", tags=["admin-settings"])


def _get_or_create_settings(db: Session) -> AdminSettings:
    settings = db.query(AdminSettings).first()
    if settings is None:
        settings = AdminSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("", response_model=AdminSettingsRead, dependencies=[Depends(get_current_user)])
def get_admin_settings(db: Session = Depends(get_db)) -> AdminSettings:
    return _get_or_create_settings(db)


@router.put("", response_model=AdminSettingsRead, dependencies=[Depends(get_current_admin_user)])
def update_admin_settings(payload: AdminSettingsUpdate, db: Session = Depends(get_db)) -> AdminSettings:
    settings = _get_or_create_settings(db)
    settings.forward_to_email = payload.forward_to_email.strip() if payload.forward_to_email else None
    db.commit()
    db.refresh(settings)
    return settings
