from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_agent_profile import ACTION_WRITER_ROLE, BRAIN_WRITER_ROLE, CHECKER_ROLE, DRAFTER_ROLE, PLANNER_ROLE, AiAgentProfile
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_ai_template_link import TenantAiTemplateLink
from app.models.user import User
from app.schemas.tenant_ai_settings import (
    BulkTenantAiTemplateAssignment,
    BulkTenantAiTemplateAssignmentResult,
    BulkTenantPlannerModeAssignment,
    BulkTenantPlannerModeAssignmentResult,
    TenantAiSettingsRead,
    TenantAiSettingsUpdate,
)

router = APIRouter(tags=["tenant-ai-settings"])


def _validated_profile_id(db: Session, profile_id: int | None, role: str) -> int | None:
    if profile_id is None:
        return None
    exists = (
        db.query(AiAgentProfile.id)
        .filter(AiAgentProfile.id == profile_id, AiAgentProfile.role == role)
        .first()
    )
    return profile_id if exists else None


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
        planner_mode=settings.planner_mode or "off",
        planner_profile_id=settings.planner_profile_id,
        checker_profile_id=settings.checker_profile_id,
        drafter_profile_id=settings.drafter_profile_id,
        brain_writer_enabled=settings.brain_writer_enabled,
        brain_writer_profile_id=settings.brain_writer_profile_id,
        action_writer_enabled=settings.action_writer_enabled,
        action_writer_profile_id=settings.action_writer_profile_id,
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
    # "auto-draft"/"auto-send" planner mode is meaningless unless the background pipeline actually
    # triggers on inbound messages, which is gated separately by auto_draft_email/whatsapp - so
    # picking either mode implies both channels' triggers are on, regardless of what the client
    # sends. Without this, a tenant can be put in "auto-draft" mode and nothing will ever happen.
    planner_mode_implies_auto_draft = payload.planner_mode in ("auto-draft", "auto-send")
    settings.auto_draft_email = payload.auto_draft_email or planner_mode_implies_auto_draft
    settings.auto_draft_whatsapp = payload.auto_draft_whatsapp or planner_mode_implies_auto_draft
    # Auto-send is meaningless without auto-draft generating something to send, and the manual
    # UI is expected to disable the auto-send toggle whenever auto-draft is off for that channel
    # — this is the server-side guarantee behind that rule, independent of what the client sends.
    # "auto-draft" planner mode carries the same guarantee: it must never schedule an auto-send,
    # regardless of what the client sends, so the toggles are force-cleared server-side too.
    auto_send_allowed = payload.planner_mode != "auto-draft"
    settings.auto_send_email = payload.auto_send_email and settings.auto_draft_email and auto_send_allowed
    settings.auto_send_whatsapp = payload.auto_send_whatsapp and settings.auto_draft_whatsapp and auto_send_allowed
    settings.planner_mode = payload.planner_mode
    # A profile id that does not exist (or is for the wrong role) is stored as "unpinned" rather
    # than rejected, so the tenant transparently falls back to the role default.
    settings.planner_profile_id = _validated_profile_id(db, payload.planner_profile_id, PLANNER_ROLE)
    settings.checker_profile_id = _validated_profile_id(db, payload.checker_profile_id, CHECKER_ROLE)
    settings.drafter_profile_id = _validated_profile_id(db, payload.drafter_profile_id, DRAFTER_ROLE)
    settings.brain_writer_enabled = payload.brain_writer_enabled
    settings.brain_writer_profile_id = _validated_profile_id(db, payload.brain_writer_profile_id, BRAIN_WRITER_ROLE)
    settings.action_writer_enabled = payload.action_writer_enabled
    settings.action_writer_profile_id = _validated_profile_id(db, payload.action_writer_profile_id, ACTION_WRITER_ROLE)

    db.commit()
    db.refresh(settings)
    return _to_read(db, settings)


@router.post("/tenant-ai-settings/bulk-templates", response_model=BulkTenantAiTemplateAssignmentResult)
def bulk_update_tenant_ai_templates(
    payload: BulkTenantAiTemplateAssignment,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkTenantAiTemplateAssignmentResult:
    tenant_ids = sorted(set(payload.tenant_ids))
    template_ids = sorted(set(payload.template_ids))
    if not tenant_ids or not template_ids:
        return BulkTenantAiTemplateAssignmentResult(tenants_affected=0, links_added=0, links_removed=0)

    if payload.action == "add":
        existing_pairs = {
            (row.tenant_id, row.template_id)
            for row in db.query(TenantAiTemplateLink)
            .filter(TenantAiTemplateLink.tenant_id.in_(tenant_ids), TenantAiTemplateLink.template_id.in_(template_ids))
            .all()
        }
        links_added = 0
        for tenant_id in tenant_ids:
            for template_id in template_ids:
                if (tenant_id, template_id) not in existing_pairs:
                    db.add(TenantAiTemplateLink(tenant_id=tenant_id, template_id=template_id))
                    links_added += 1
        db.commit()
        return BulkTenantAiTemplateAssignmentResult(tenants_affected=len(tenant_ids), links_added=links_added, links_removed=0)

    # action == "remove": also clear any default-template pointer left dangling by the removal,
    # since this bypasses the per-tenant settings form that would otherwise keep them in sync.
    links_removed = (
        db.query(TenantAiTemplateLink)
        .filter(TenantAiTemplateLink.tenant_id.in_(tenant_ids), TenantAiTemplateLink.template_id.in_(template_ids))
        .delete(synchronize_session=False)
    )
    affected_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id.in_(tenant_ids)).all()
    for settings in affected_settings:
        if settings.default_email_template_id in template_ids:
            settings.default_email_template_id = None
        if settings.default_whatsapp_template_id in template_ids:
            settings.default_whatsapp_template_id = None
    db.commit()
    return BulkTenantAiTemplateAssignmentResult(tenants_affected=len(tenant_ids), links_added=0, links_removed=links_removed)


@router.post("/tenant-ai-settings/bulk-planner-mode", response_model=BulkTenantPlannerModeAssignmentResult)
def bulk_update_tenant_planner_mode(
    payload: BulkTenantPlannerModeAssignment,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkTenantPlannerModeAssignmentResult:
    tenant_ids = sorted(set(payload.tenant_ids))
    if not tenant_ids:
        return BulkTenantPlannerModeAssignmentResult(tenants_affected=0)

    # Matches the single-tenant update endpoint's server-side guarantees: "auto-draft"/"auto-send"
    # implies the trigger toggles are on (otherwise the mode does nothing), and "auto-draft" must
    # never leave a tenant scheduling auto-sends — independent of what was set before the bulk run.
    planner_mode_implies_auto_draft = payload.planner_mode in ("auto-draft", "auto-send")
    auto_send_allowed = payload.planner_mode != "auto-draft"

    for tenant_id in tenant_ids:
        settings = _get_or_create_settings(db, tenant_id)
        settings.planner_mode = payload.planner_mode
        if planner_mode_implies_auto_draft:
            settings.auto_draft_email = True
            settings.auto_draft_whatsapp = True
        if not auto_send_allowed:
            settings.auto_send_email = False
            settings.auto_send_whatsapp = False

    db.commit()
    return BulkTenantPlannerModeAssignmentResult(tenants_affected=len(tenant_ids))
