import logging

from sqlalchemy.orm import Session

from app.models.ai_auto_draft import AiAutoDraft
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import ai_agent_orchestrator, ai_auto_draft_service
from app.services.attachment_service import (
    AttachmentLimitExceededError,
    AttachmentNotFoundError,
    load_outbound_attachments,
)
from app.services.gemini_client import GeminiClientError

logger = logging.getLogger(__name__)


def run_ai_plan_for_draft(
    db: Session,
    *,
    draft_id: int,
    tenant_id: int,
    channel: str,
    operator_note: str | None,
    attachment_ids: list[int],
    user_id: int | None,
) -> None:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).first()
    if tenant is None or draft is None:
        return

    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant_id).first()
    if ai_settings is None or (ai_settings.planner_mode or "off") == "off":
        draft.status = "needs_review"
        draft.generated_text = draft.generated_text or ""
        draft.checker_feedback = "Planner is turned off for this tenant."
        db.commit()
        return

    try:
        outbound_attachments = load_outbound_attachments(
            db, tenant_id=tenant.id, attachment_ids=attachment_ids, channel=channel
        )
    except (AttachmentNotFoundError, AttachmentLimitExceededError) as exc:
        draft.status = "needs_review"
        draft.generated_text = draft.generated_text or ""
        draft.checker_feedback = str(exc)
        db.commit()
        return

    try:
        inbound_text = ai_agent_orchestrator.latest_inbound_text(db, tenant_id, channel)
        result = ai_agent_orchestrator.run_planner_loop(
            db,
            tenant=tenant,
            channel=channel,
            mode="manual",
            inbound_text=inbound_text,
            operator_note=operator_note,
            attachments=outbound_attachments,
            user_id=user_id,
        )
    except GeminiClientError as exc:
        draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).first()
        if draft is None:
            return
        draft.status = "needs_review"
        draft.generated_text = draft.generated_text or ""
        draft.checker_feedback = str(exc)
        db.commit()
        logger.exception("AI planner run failed draft_id=%s", draft_id)
        return

    draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).first()
    if draft is None:
        return

    if result.generated_text:
        ai_auto_draft_service.apply_planner_result_to_draft(
            db,
            draft,
            tenant=tenant,
            ai_settings=ai_settings,
            channel=channel,
            result=result,
            inbound_text=inbound_text,
        )
    else:
        draft.status = result.status
        draft.template_id = result.template_id
        draft.agent_run_id = result.run_id
        draft.checker_feedback = result.checker_feedback
        draft.generated_text = draft.generated_text or ""
        draft.scheduled_send_at = None
    db.commit()
