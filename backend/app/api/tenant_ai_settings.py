from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_ai_template_link import TenantAiTemplateLink
from app.models.user import User
from app.schemas.tenant_ai_settings import TenantAiSettingsRead, TenantAiSettingsUpdate

router = APIRouter(tags=["tenant-ai-settings"])


def _get_or_create_settings(db: Session, tenant_id: int) -> TenantAiSettings:
    settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if settings is None:
        settings = TenantAiSettings(tenant_id=tenant_id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _to_read(db: Session, settings: TenantAiSettings) -> TenantAiSettingsRead:
    available_template_ids = [
        row.template_id
        for row in db.query(TenantAiTemplateLink).filter(TenantAiTemplateLink.tenant_id == settings.tenant_id).all()
    ]
    return TenantAiSettingsRead(
        tenant_id=settings.tenant_id,
        available_template_ids=available_template_ids,
        default_email_template_id=settings.default_email_template_id,
        default_whatsapp_template_id=settings.default_whatsapp_template_id,
        auto_draft_email=settings.auto_draft_email,
        auto_draft_whatsapp=settings.auto_draft_whatsapp,
        auto_send_email=settings.auto_send_email,
        auto_send_whatsapp=settings.auto_send_whatsapp,
    )


@router.get("/tenants/{tenant_id}/ai-settings", response_model=TenantAiSettingsRead)
def get_tenant_ai_settings(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantAiSettingsRead:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    settings = _get_or_create_settings(db, tenant_id)
    return _to_read(db, settings)


@router.put("/tenants/{tenant_id}/ai-settings", response_model=TenantAiSettingsRead)
def update_tenant_ai_settings(
    tenant_id: int,
    payload: TenantAiSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantAiSettingsRead:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    settings = _get_or_create_settings(db, tenant_id)

    requested_ids = set(payload.available_template_ids)
    if payload.default_email_template_id is not None:
        requested_ids.add(payload.default_email_template_id)
    if payload.default_whatsapp_template_id is not None:
        requested_ids.add(payload.default_whatsapp_template_id)

    existing_links = db.query(TenantAiTemplateLink).filter(TenantAiTemplateLink.tenant_id == tenant_id).all()
    existing_ids = {link.template_id for link in existing_links}
    for link in existing_links:
        if link.template_id not in requested_ids:
            db.delete(link)
    for template_id in requested_ids - existing_ids:
        db.add(TenantAiTemplateLink(tenant_id=tenant_id, template_id=template_id))

    settings.default_email_template_id = payload.default_email_template_id
    settings.default_whatsapp_template_id = payload.default_whatsapp_template_id
    settings.auto_draft_email = payload.auto_draft_email
    settings.auto_draft_whatsapp = payload.auto_draft_whatsapp
    # Auto-send is meaningless without auto-draft generating something to send, and the manual
    # UI is expected to disable the auto-send toggle whenever auto-draft is off for that channel
    # — this is the server-side guarantee behind that rule, independent of what the client sends.
    settings.auto_send_email = payload.auto_send_email and payload.auto_draft_email
    settings.auto_send_whatsapp = payload.auto_send_whatsapp and payload.auto_draft_whatsapp

    db.commit()
    db.refresh(settings)
    return _to_read(db, settings)
