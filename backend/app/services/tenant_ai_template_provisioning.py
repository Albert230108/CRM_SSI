from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.ai_reply_template import AiReplyTemplate
from app.models.tenant_ai_template_link import TenantAiTemplateLink


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
