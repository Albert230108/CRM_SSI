import asyncio
import logging

from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_approval_request import AiAutoDraftApprovalRequest
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.user import User
from app.services.whatsapp_client import WhatsAppBridgeError, send_system_whatsapp_message

logger = logging.getLogger(__name__)


def _build_message(*, tenant_name: str, draft: AiAutoDraft) -> str:
    text = draft.generated_text.strip()

    header = f"New AI draft — {tenant_name} ({draft.channel})"
    if draft.status == "needs_review":
        header = "⚠️ Needs review — " + header
    else:
        header = "🤖 " + header

    return (
        f'{header}\n\n"{text}"\n\n'
        f"Reply YES-{draft.id} to send\n"
        f"Reply NO-{draft.id} to dismiss"
    )


def notify_admins_of_new_draft(db: Session, draft: AiAutoDraft | None) -> None:
    """Pings every opted-in staff member individually on WhatsApp when an "auto-draft" mode
    draft is ready, so it doesn't just sit unnoticed on the AI Drafts page.

    Only fires for planner_mode == "auto-draft": that is the one mode where a draft is
    generated but never auto-sent, so it always needs an explicit human decision. Does not
    commit on its own failure path for the caller's outer transaction, but does commit the
    approval-request rows it writes once sends are attempted.
    """
    if draft is None:
        return

    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == draft.tenant_id).first()
    if ai_settings is None or (ai_settings.planner_mode or "off") != "auto-draft":
        return
    if draft.status not in ("pending", "needs_review"):
        return

    recipients = (
        db.query(User)
        .filter(User.whatsapp_notifications_enabled.is_(True), User.is_active.is_(True), User.phone.isnot(None))
        .all()
    )
    if not recipients:
        return

    settings = db.query(AdminSettings).first()
    external_account_id = settings.notification_whatsapp_external_account_id if settings is not None else None
    if not external_account_id:
        logger.info(
            "Skipping AI draft approval notification: no notification_whatsapp_external_account_id configured draft_id=%s",
            draft.id,
        )
        return

    tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
    tenant_name = tenant.name if tenant is not None else "Unknown tenant"
    message = _build_message(tenant_name=tenant_name, draft=draft)

    for user in recipients:
        phone = (user.phone or "").strip()
        if not phone:
            continue
        try:
            asyncio.run(send_system_whatsapp_message(to=phone, message=message, external_account_id=external_account_id))
        except WhatsAppBridgeError:
            logger.exception(
                "Failed to send AI draft approval notification draft_id=%s user_id=%s", draft.id, user.id
            )
            continue
        db.add(
            AiAutoDraftApprovalRequest(
                ai_auto_draft_id=draft.id,
                user_id=user.id,
                phone=phone,
                external_account_id=external_account_id,
            )
        )

    db.commit()
