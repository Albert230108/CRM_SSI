from app.models.admin_settings import AdminSettings
from app.models.ai_reply_template import AiReplyTemplate
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant import Tenant
from app.models.tenant_ai_template_link import TenantAiTemplateLink
from app.models.user import User
from app.services.tenant_ai_template_provisioning import (
    apply_default_ai_templates_if_enabled,
    apply_default_formatter_settings,
)


def _create_template(db_session, name="Template"):
    user = User(email=f"{name.lower().replace(' ', '-')}@example.com", password_hash="x", is_active=True, is_admin=False)
    db_session.add(user)
    db_session.flush()
    template = AiReplyTemplate(name=name, sections=[{"label": "Persona", "content": "Be helpful."}], created_by_user_id=user.id)
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def test_does_nothing_when_admin_setting_is_off(db_session):
    _create_template(db_session, "Provisioning Template A")
    tenant = Tenant(name="Provisioning Tenant A", booking_id="B-provision-1")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    apply_default_ai_templates_if_enabled(db_session, tenant.id)
    db_session.commit()

    assert db_session.query(TenantAiTemplateLink).filter(TenantAiTemplateLink.tenant_id == tenant.id).count() == 0


def test_links_every_existing_template_when_enabled(db_session):
    template_a = _create_template(db_session, "Provisioning Template B")
    template_b = _create_template(db_session, "Provisioning Template C")
    db_session.add(AdminSettings(ai_auto_apply_templates_to_new_tenants=True))
    db_session.commit()

    tenant = Tenant(name="Provisioning Tenant B", booking_id="B-provision-2")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    apply_default_ai_templates_if_enabled(db_session, tenant.id)
    db_session.commit()

    linked_ids = {
        row.template_id
        for row in db_session.query(TenantAiTemplateLink).filter(TenantAiTemplateLink.tenant_id == tenant.id).all()
    }
    assert linked_ids == {template_a.id, template_b.id}


def test_formatter_default_seeds_new_tenant_settings_when_enabled(db_session):
    db_session.add(AdminSettings(formatter_default_enabled=True))
    db_session.commit()

    tenant = Tenant(name="Provisioning Tenant C", booking_id="B-provision-3")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    apply_default_formatter_settings(db_session, tenant.id)
    db_session.commit()

    settings = db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).one()
    assert settings.formatter_enabled is True
