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
    if payload.ai_draft_debounce_seconds is not None:
        settings.ai_draft_debounce_seconds = payload.ai_draft_debounce_seconds
    if payload.ai_auto_send_delay_seconds is not None:
        settings.ai_auto_send_delay_seconds = payload.ai_auto_send_delay_seconds
    if payload.ai_auto_apply_templates_to_new_tenants is not None:
        settings.ai_auto_apply_templates_to_new_tenants = payload.ai_auto_apply_templates_to_new_tenants
    if payload.planner_default_mode is not None:
        settings.planner_default_mode = payload.planner_default_mode
    if payload.brain_writer_default_enabled is not None:
        settings.brain_writer_default_enabled = payload.brain_writer_default_enabled
    if payload.action_writer_default_enabled is not None:
        settings.action_writer_default_enabled = payload.action_writer_default_enabled
    if payload.ai_daily_token_cap is not None:
        # Omitting the field leaves the cap alone; sending 0 is how the UI clears it, since a
        # null would be indistinguishable from "not included in this partial update".
        settings.ai_daily_token_cap = payload.ai_daily_token_cap or None
    if payload.notification_whatsapp_debounce_seconds is not None:
        settings.notification_whatsapp_debounce_seconds = payload.notification_whatsapp_debounce_seconds
    if payload.clear_notification_whatsapp_external_account_id:
        settings.notification_whatsapp_external_account_id = None
    elif payload.notification_whatsapp_external_account_id is not None:
        settings.notification_whatsapp_external_account_id = payload.notification_whatsapp_external_account_id
    db.commit()
    db.refresh(settings)
    return settings
