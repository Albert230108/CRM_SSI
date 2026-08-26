from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.ai_reply_template import AiReplyTemplate
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_ai_template_link import TenantAiTemplateLink


def apply_default_planner_mode(db: Session, tenant_id: int) -> None:
    """Give a newly created tenant the admin-configured starting planner mode.

    Only new tenants are seeded - existing ones are never retro-fitted - so switching the
    default cannot silently start drafting for bookings already in flight. Does not commit.
    """
    settings = db.query(AdminSettings).first()
    mode = (settings.planner_default_mode if settings is not None else "off") or "off"
    if mode == "off":
        return

    tenant_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if tenant_settings is None:
        tenant_settings = TenantAiSettings(tenant_id=tenant_id)
        db.add(tenant_settings)
    tenant_settings.planner_mode = mode


def apply_default_brain_action_writer_settings(db: Session, tenant_id: int) -> None:
    """Seed the brain/action writer toggles for a newly created tenant.

    Only new tenants are affected - existing tenants are never retro-fitted - so changing the
    admin defaults cannot silently enable AI for live tenants. Does not commit.
    """
    settings = db.query(AdminSettings).first()
    if settings is None:
        return

    brain_enabled = bool(settings.brain_writer_default_enabled)
    action_enabled = bool(settings.action_writer_default_enabled)
    if not brain_enabled and not action_enabled:
        return

    tenant_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if tenant_settings is None:
        tenant_settings = TenantAiSettings(tenant_id=tenant_id)
        db.add(tenant_settings)
    if brain_enabled:
        tenant_settings.brain_writer_enabled = True
    if action_enabled:
        tenant_settings.action_writer_enabled = True


def apply_default_formatter_settings(db: Session, tenant_id: int) -> None:
    """Seed the formatter toggle for a newly created tenant.

    Only new tenants are affected - existing tenants are never retro-fitted - so changing the
    admin default cannot silently enable rich formatting for live tenants. Does not commit.
    """
    settings = db.query(AdminSettings).first()
    if settings is None or not settings.formatter_default_enabled:
        return

    # Flush any earlier seeding helpers in the same transaction so we can reuse the same
    # TenantAiSettings row instead of racing ourselves into a duplicate insert.
    db.flush()
    tenant_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if tenant_settings is None:
        tenant_settings = TenantAiSettings(tenant_id=tenant_id)
        db.add(tenant_settings)
    tenant_settings.formatter_enabled = True


def apply_default_ai_templates_if_enabled(db: Session, tenant_id: int) -> None:
    """Links a newly created tenant to every existing shared AI reply template.

    Only takes effect when an admin has opted into `ai_auto_apply_templates_to_new_tenants`
    (Admin Settings) - by default a new tenant starts with no templates available, matching
    the existing manual-linking-only convention for other per-tenant AI config. Does not
    commit; the caller (tenant creation/import) owns the transaction.
    """
    settings = db.query(AdminSettings).first()
    if settings is None or not settings.ai_auto_apply_templates_to_new_tenants:
        return

    template_ids = [row.id for row in db.query(AiReplyTemplate.id).all()]
    if not template_ids:
        return

    existing_ids = {
        row.template_id
        for row in db.query(TenantAiTemplateLink.template_id).filter(TenantAiTemplateLink.tenant_id == tenant_id).all()
    }
    for template_id in template_ids:
        if template_id not in existing_ids:
            db.add(TenantAiTemplateLink(tenant_id=tenant_id, template_id=template_id))
