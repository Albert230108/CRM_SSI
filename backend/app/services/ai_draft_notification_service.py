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
        f"Reply NO-{draft.id} to dismiss\n"
        f"Reply REDO-{draft.id} <what to change> to regenerate"
    )


def _resolve_notification_targets(
    db: Session, draft: AiAutoDraft
) -> tuple[list[User], str, str] | None:
    """Recipients, external_account_id, and tenant_name for messaging about `draft`, or None
    if there's nothing to notify (no opted-in recipients or no notification account configured).
    """
    recipients = (
        db.query(User)
        .filter(User.whatsapp_notifications_enabled.is_(True), User.is_active.is_(True), User.phone.isnot(None))
        .all()
    )
    if not recipients:
        return None

    settings = db.query(AdminSettings).first()
    external_account_id = settings.notification_whatsapp_external_account_id if settings is not None else None
    if not external_account_id:
        logger.info(
            "Skipping AI draft notification: no notification_whatsapp_external_account_id configured draft_id=%s",
            draft.id,
        )
        return None

    tenant = db.query(Tenant).filter(Tenant.id == draft.tenant_id).first()
    tenant_name = tenant.name if tenant is not None else "Unknown tenant"
    return recipients, external_account_id, tenant_name


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

    targets = _resolve_notification_targets(db, draft)
    if targets is None:
        return
    recipients, external_account_id, tenant_name = targets
    message = _build_message(tenant_name=tenant_name, draft=draft)

    for user in recipients:
        phone = (user.phone or "").strip()
        if not phone:
            continue
        try:
            send_result = asyncio.run(
                send_system_whatsapp_message(to=phone, message=message, external_account_id=external_account_id)
            )
        except WhatsAppBridgeError:
            logger.exception(
                "Failed to send AI draft approval notification draft_id=%s user_id=%s", draft.id, user.id
            )
            continue

        # The bridge reports the recipient's @lid identity when their account uses one; without
        # it their reply arrives from an identity their stored phone number cannot match.
        identity_key = send_result.get("whatsapp_identity_key") if isinstance(send_result, dict) else None
        if identity_key and user.whatsapp_identity_key != identity_key:
            user.whatsapp_identity_key = identity_key

        db.add(
            AiAutoDraftApprovalRequest(
                ai_auto_draft_id=draft.id,
                user_id=user.id,
                phone=phone,
                external_account_id=external_account_id,
            )
        )

    db.commit()


def notify_admins_of_redraft(db: Session, draft: AiAutoDraft) -> None:
    """Re-broadcasts a regenerated draft (after a "REDO-{id}" reply) to every opted-in staff
    member under the same draft id, resetting each existing approval request back to
    unresponded so YES/NO/REDO all work again for everyone - including whoever asked for the redo.

    Unlike `notify_admins_of_new_draft`, this doesn't gate on planner_mode or draft.status:
    it's only ever called right after a successful regenerate, where both are already known-good.
    """
    targets = _resolve_notification_targets(db, draft)
    if targets is None:
        return
    recipients, external_account_id, tenant_name = targets
    message = _build_message(tenant_name=tenant_name, draft=draft)

    for user in recipients:
        phone = (user.phone or "").strip()
        if not phone:
            continue
        try:
            send_result = asyncio.run(
                send_system_whatsapp_message(to=phone, message=message, external_account_id=external_account_id)
            )
        except WhatsAppBridgeError:
            logger.exception(
                "Failed to send AI draft redo notification draft_id=%s user_id=%s", draft.id, user.id
            )
            continue

        identity_key = send_result.get("whatsapp_identity_key") if isinstance(send_result, dict) else None
        if identity_key and user.whatsapp_identity_key != identity_key:
            user.whatsapp_identity_key = identity_key

        approval_request = (
            db.query(AiAutoDraftApprovalRequest)
            .filter(
                AiAutoDraftApprovalRequest.ai_auto_draft_id == draft.id,
                AiAutoDraftApprovalRequest.user_id == user.id,
            )
            .first()
        )
        if approval_request is not None:
            approval_request.responded_at = None
            approval_request.response = None
            approval_request.phone = phone
            approval_request.external_account_id = external_account_id
        else:
            db.add(
                AiAutoDraftApprovalRequest(
                    ai_auto_draft_id=draft.id,
                    user_id=user.id,
                    phone=phone,
                    external_account_id=external_account_id,
                )
            )

    db.commit()
