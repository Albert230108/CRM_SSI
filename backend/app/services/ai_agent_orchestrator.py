"""The planner -> drafter -> checker loop.

A single entry point, `run_planner_loop`, owns the whole decision: which template fits the
conversation, what extra knowledge to pull from the brain, what extra instruction the drafter
needs, and whether the resulting draft is good enough to hand over. Every model call is recorded
on an `AiAgentRun` so an operator can audit the choice after the fact.

The loop never sends anything. It returns text plus a status; persisting a draft, showing it in
the reply box, or scheduling an auto-send is the caller's job.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.ai_agent_profile import CHECKER_ROLE, PLANNER_ROLE, AiAgentProfile
from app.models.ai_agent_run import (
    STATUS_COMPLETED,
    STATUS_ESCALATED,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_SKIPPED,
    AiAgentRun,
    AiAgentRunStep,
)
from app.models.ai_reply_template import AiReplyTemplate
from app.models.gmail_integration import ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant_ai_settings import TenantAiSettings
from app.services import ai_reply_service, brain_service, gemini_client
from app.services.thread_timeline_service import load_tenant_whatsapp_messages

logger = logging.getLogger(__name__)

PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "should_reply": {"type": "boolean"},
        "template_id": {"type": ["integer", "null"]},
        "extra_brain_sections": {"type": "array", "items": {"type": "string"}},
        "extra_instructions": {"type": "string"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "template_id": {"type": "integer"},
                    "why_not": {"type": "string"},
                },
                "required": ["template_id", "why_not"],
            },
        },
    },
    "required": ["should_reply", "template_id", "extra_instructions", "confidence", "reasoning"],
}

CHECKER_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "feedback": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["passed", "feedback"],
}


@dataclass
class PlannerRunResult:
    status: str
    run_id: int | None = None
    generated_text: str | None = None
    template_id: int | None = None
    checker_passed: bool = False
    checker_feedback: str | None = None
    escalation_reason: str | None = None
    attempts: int = 0
    # True only when the checker approved the draft; the auto pipeline refuses to send otherwise.
    auto_send_allowed: bool = False


@dataclass
class _RunRecorder:
    """Accumulates steps and totals for one run, so the loop body stays free of bookkeeping."""

    run: AiAgentRun
    db: Session
    started: float = field(default_factory=time.monotonic)
    _index: int = 0

    def record(
        self,
        stage: str,
        *,
        prompt: str,
        result: gemini_client.GenerationResult | None = None,
        error: str | None = None,
        model: str | None = None,
    ) -> None:
        step = AiAgentRunStep(
            run_id=self.run.id,
            step_index=self._index,
            stage=stage,
            model=result.model if result is not None else model,
            prompt=prompt,
            response=result.text if result is not None else None,
            parsed=result.parsed if result is not None else None,
            prompt_tokens=result.prompt_tokens if result is not None else None,
            output_tokens=result.output_tokens if result is not None else None,
            latency_ms=result.latency_ms if result is not None else None,
            error=error,
        )
        self.db.add(step)
        self._index += 1
        if result is not None:
            self.run.total_prompt_tokens += result.prompt_tokens or 0
            self.run.total_output_tokens += result.output_tokens or 0

    def finish(self, status: str, **fields) -> None:
        self.run.status = status
        self.run.duration_ms = int((time.monotonic() - self.started) * 1000)
        for key, value in fields.items():
            setattr(self.run, key, value)


def resolve_profile(db: Session, role: str, pinned_id: int | None) -> AiAgentProfile | None:
    """A tenant's pinned profile if it is still usable, otherwise the role's active default."""
    if pinned_id is not None:
        pinned = (
            db.query(AiAgentProfile)
            .filter(AiAgentProfile.id == pinned_id, AiAgentProfile.role == role, AiAgentProfile.is_active.is_(True))
            .first()
        )
        if pinned is not None:
            return pinned
    return (
        db.query(AiAgentProfile)
        .filter(
            AiAgentProfile.role == role,
            AiAgentProfile.is_default.is_(True),
            AiAgentProfile.is_active.is_(True),
        )
        .first()
    )


def tokens_spent_today(db: Session) -> int:
    """Total planner/checker tokens billed since midnight UTC, across every tenant."""
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    totals = (
        db.query(
            func.coalesce(func.sum(AiAgentRun.total_prompt_tokens), 0),
            func.coalesce(func.sum(AiAgentRun.total_output_tokens), 0),
        )
        .filter(AiAgentRun.created_at >= midnight)
        .first()
    )
    return int(totals[0] or 0) + int(totals[1] or 0)


def _daily_cap(db: Session, profiles: list[AiAgentProfile | None]) -> int | None:
    """The tightest cap in force: the global admin one and any the profiles impose."""
    caps = [profile.daily_token_cap for profile in profiles if profile is not None and profile.daily_token_cap]
    settings = db.query(AdminSettings).first()
    if settings is not None and settings.ai_daily_token_cap:
        caps.append(int(settings.ai_daily_token_cap))
    return min(caps) if caps else None


def _matched_keywords(profile: AiAgentProfile, text: str) -> list[str]:
    haystack = (text or "").lower()
    keywords = profile.escalate_keywords or []
    return [str(word) for word in keywords if str(word).strip() and str(word).strip().lower() in haystack]


def latest_inbound_text(db: Session, tenant_id: int, channel: str) -> str | None:
    """The message the planner is reacting to, so guardrails and prompts have something concrete."""
    if channel == "email":
        message = (
            db.query(ConversationMessage)
            .join(TenantConversationLink, TenantConversationLink.conversation_id == ConversationMessage.conversation_id)
            .filter(
                TenantConversationLink.tenant_id == tenant_id,
                TenantConversationLink.unlinked_at.is_(None),
                ConversationMessage.direction == "inbound",
            )
            .order_by(ConversationMessage.sent_at.desc(), ConversationMessage.id.desc())
            .first()
        )
        return (message.body or "").strip() if message is not None else None

    messages = [
        message
        for message in load_tenant_whatsapp_messages(db, tenant_id)
        if message.direction == "inbound"
    ]
    return (messages[-1].message or "").strip() if messages else None


def _resolve_history_channels(profile: AiAgentProfile, channel: str) -> str:
    """"inbound" means "whichever channel this message arrived on"; everything else is literal."""
    configured = (profile.history_channels or "both").strip()
    if configured == "inbound":
        return channel if channel in ("email", "whatsapp") else "both"
    return configured if configured in ("both", "email", "whatsapp") else "both"


def _build_context_blocks(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    channel: str,
    inbound_text: str | None,
) -> list[str]:
    """The shared context every agent gets, sized by its own profile's budget."""
    blocks: list[str] = []
    limit = max(0, int(profile.history_limit or 0))
    if limit:
        blocks.append(
            ai_reply_service._build_history_context(
                db,
                tenant,
                limit,
                channels=_resolve_history_channels(profile, channel),
                lookback_days=profile.history_lookback_days,
            )
        )
    if profile.include_beds24:
        blocks.append(ai_reply_service._build_beds24_context(tenant))
    if profile.include_payments:
        blocks.append(ai_reply_service._build_payments_context(db, tenant))
    if profile.include_notes:
        blocks.append(ai_reply_service._build_notes_context(tenant))
    if inbound_text:
        blocks.append(f"## Message To Answer\n{inbound_text}")
    return blocks


def _template_catalogue(db: Session, tenant_id: int) -> tuple[str, set[int]]:
    """The templates the planner may choose from, restricted to what this tenant has available.

    Returns the rendered catalogue and the allowed id set, so a hallucinated id can be rejected
    rather than silently drafting from a template the operator never enabled for this tenant.
    """
    from app.models.tenant_ai_template_link import TenantAiTemplateLink

    linked_ids = {
        row[0]
        for row in db.query(TenantAiTemplateLink.template_id)
        .filter(TenantAiTemplateLink.tenant_id == tenant_id)
        .all()
    }
    query = db.query(AiReplyTemplate).order_by(AiReplyTemplate.name)
    templates = [template for template in query.all() if not linked_ids or template.id in linked_ids]
    if not templates:
        return "No templates are available for this tenant.", set()

    lines = [
        f"- id={template.id} | {template.name} | {(template.description or '').strip() or 'No description provided.'}"
        for template in templates
    ]
    return "\n".join(lines), {template.id for template in templates}


def _language_directive(profile: AiAgentProfile) -> str | None:
    if not profile.match_inbound_language:
        return None
    return "The reply must be written in the same language the guest used in their latest message."


def _build_planner_prompt(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    catalogue: str,
    channel: str,
    inbound_text: str | None,
    operator_note: str | None,
) -> str:
    blocks = [
        "You are the planner for a short-stay rental CRM. Read the conversation and decide how to "
        "reply. Choose exactly one template from the catalogue, name any extra knowledge-base "
        "sections the reply needs, and write the concrete instruction the drafting model should "
        "follow. Do not write the reply itself."
    ]
    instructions = (profile.instructions or "").strip()
    if instructions:
        blocks.append(f"## Your Instructions\n{instructions}")

    directive = _language_directive(profile)
    if directive:
        blocks.append(f"## Language\n{directive}")

    blocks.append(f"## Template Catalogue\nPick `template_id` from this list only.\n{catalogue}")

    if profile.include_brain_index:
        blocks.append(
            "## Knowledge Base Index\n"
            "Put any paths the reply needs into `extra_brain_sections`. Referencing a parent path "
            "also pulls in everything nested under it.\n"
            + brain_service.build_brain_index(db)
        )

    blocks += _build_context_blocks(db, tenant, profile, channel=channel, inbound_text=inbound_text)

    note = (operator_note or "").strip()
    if note:
        blocks.append(
            "## Operator Note\n"
            "A member of staff typed this into the reply box before asking for a draft. Treat it as "
            "the strongest signal about what the reply must contain.\n"
            f"{note}"
        )

    blocks.append(
        "## Output\n"
        "Return JSON only. `confidence` is 0-1 for how well the chosen template fits. `reasoning` "
        "explains why you chose it. `alternatives` lists the other templates you seriously "
        "considered and why you rejected each. Set `should_reply` to false if no reply is warranted."
    )
    return "\n\n".join(blocks)


def _build_checker_prompt(
    db: Session,
    tenant: Tenant,
    profile: AiAgentProfile,
    *,
    channel: str,
    draft: str,
    inbound_text: str | None,
    plan_instructions: str,
) -> str:
    blocks = [
        "You are the reviewer for a short-stay rental CRM. Proof-read the draft reply below "
        "against your instructions and the conversation. You do not rewrite the reply - you "
        "either approve it or explain precisely what must change."
    ]
    instructions = (profile.instructions or "").strip()
    if instructions:
        blocks.append(f"## Your Instructions\n{instructions}")

    directive = _language_directive(profile)
    if directive:
        blocks.append(f"## Language\n{directive}")

    if plan_instructions.strip():
        blocks.append(f"## What The Draft Was Asked To Do\n{plan_instructions.strip()}")

    blocks += _build_context_blocks(db, tenant, profile, channel=channel, inbound_text=inbound_text)
    blocks.append(f"## Draft To Review\n{draft}")
    blocks.append(
        "## Output\n"
        "Return JSON only. Set `passed` to true only if the draft can be sent as-is. When it "
        "cannot, `feedback` must be specific enough for the writer to fix it in one pass, and "
        "`issues` should list each problem separately."
    )
    return "\n\n".join(blocks)


def run_planner_loop(
    db: Session,
    *,
    tenant: Tenant,
    channel: str,
    mode: str,
    inbound_text: str | None = None,
    operator_note: str | None = None,
    user_id: int | None = None,
) -> PlannerRunResult:
    """Plan, draft and review a reply. Adds an AiAgentRun to the session but does not commit."""
    ai_settings = db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    planner_profile = resolve_profile(db, PLANNER_ROLE, ai_settings.planner_profile_id if ai_settings else None)
    checker_profile = resolve_profile(db, CHECKER_ROLE, ai_settings.checker_profile_id if ai_settings else None)

    run = AiAgentRun(
        tenant_id=tenant.id,
        channel=channel,
        mode=mode,
        status=STATUS_FAILED,
        planner_profile_id=planner_profile.id if planner_profile else None,
        checker_profile_id=checker_profile.id if checker_profile else None,
        created_by_user_id=user_id,
    )
    db.add(run)
    # Flush so run.id exists for the step rows; the caller still owns the commit.
    db.flush()
    recorder = _RunRecorder(run=run, db=db)

    if planner_profile is None:
        recorder.finish(STATUS_FAILED, escalation_reason="no_planner_profile")
        return PlannerRunResult(status=STATUS_FAILED, run_id=run.id, escalation_reason="no_planner_profile")

    # Guardrail first: a message about refunds or lawyers should never reach the model at all.
    matched = _matched_keywords(planner_profile, inbound_text or "")
    if matched:
        reason = f"keyword:{matched[0]}"
        recorder.finish(STATUS_ESCALATED, escalation_reason=reason)
        return PlannerRunResult(status=STATUS_ESCALATED, run_id=run.id, escalation_reason=reason)

    cap = _daily_cap(db, [planner_profile, checker_profile])
    if cap is not None and tokens_spent_today(db) >= cap:
        recorder.finish(STATUS_ESCALATED, escalation_reason="token_cap")
        return PlannerRunResult(status=STATUS_ESCALATED, run_id=run.id, escalation_reason="token_cap")

    catalogue, allowed_template_ids = _template_catalogue(db, tenant.id)
    planner_prompt = _build_planner_prompt(
        db,
        tenant,
        planner_profile,
        catalogue=catalogue,
        channel=channel,
        inbound_text=inbound_text,
        operator_note=operator_note,
    )
    try:
        planner_result = gemini_client.generate(
            planner_prompt,
            model=planner_profile.model,
            temperature=planner_profile.temperature,
            max_output_tokens=planner_profile.max_output_tokens,
            response_schema=PLANNER_SCHEMA,
        )
    except gemini_client.GeminiClientError as exc:
        recorder.record("planner", prompt=planner_prompt, error=str(exc), model=planner_profile.model)
        recorder.finish(STATUS_FAILED, escalation_reason="planner_error")
        return PlannerRunResult(status=STATUS_FAILED, run_id=run.id, escalation_reason="planner_error")

    recorder.record("planner", prompt=planner_prompt, result=planner_result)
    plan = planner_result.parsed or {}

    if not plan.get("should_reply", False):
        recorder.finish(STATUS_SKIPPED, escalation_reason="planner_declined")
        return PlannerRunResult(status=STATUS_SKIPPED, run_id=run.id, escalation_reason="planner_declined")

    template_id = plan.get("template_id")
    confidence = float(plan.get("confidence") or 0.0)
    no_match = template_id is None or template_id not in allowed_template_ids
    if no_match or confidence < float(planner_profile.min_confidence or 0.0):
        reason = "no_template_match" if no_match else "low_confidence"
        # `skip` produces nothing at all; `escalate` parks the conversation for a human.
        status = STATUS_SKIPPED if planner_profile.on_no_template_match == "skip" else STATUS_ESCALATED
        recorder.finish(status, escalation_reason=reason)
        return PlannerRunResult(status=status, run_id=run.id, escalation_reason=reason)

    template = db.query(AiReplyTemplate).filter(AiReplyTemplate.id == template_id).first()
    if template is None:
        recorder.finish(STATUS_ESCALATED, escalation_reason="no_template_match")
        return PlannerRunResult(status=STATUS_ESCALATED, run_id=run.id, escalation_reason="no_template_match")

    extra_sections = [str(path) for path in (plan.get("extra_brain_sections") or [])]
    plan_instructions = str(plan.get("extra_instructions") or "").strip()
    # The operator's own words lead, so a manual run never has its intent overwritten by the plan.
    drafter_instruction = "\n\n".join(part for part in [(operator_note or "").strip(), plan_instructions] if part)

    # One initial draft plus the configured number of redrafts. `or` is deliberately avoided:
    # max_redraft_attempts=0 means "no redrafts", not "unset".
    redrafts = checker_profile.max_redraft_attempts if checker_profile is not None else None
    max_attempts = (int(redrafts) + 1) if redrafts is not None else 1
    feedback: str | None = None
    draft_text = ""
    checker_passed = False

    for attempt in range(1, max_attempts + 1):
        run.attempts = attempt
        draft_prompt = ai_reply_service.assemble_prompt(
            db,
            tenant=tenant,
            template=template,
            channel=channel,
            rough_draft=drafter_instruction or None,
            extra_brain_section_paths=extra_sections,
            reviewer_feedback=feedback,
        )
        try:
            draft_result = gemini_client.generate(draft_prompt)
        except gemini_client.GeminiClientError as exc:
            recorder.record("drafter", prompt=draft_prompt, error=str(exc))
            recorder.finish(STATUS_FAILED, escalation_reason="drafter_error", final_template_id=template.id)
            return PlannerRunResult(
                status=STATUS_FAILED, run_id=run.id, template_id=template.id, escalation_reason="drafter_error"
            )
        recorder.record("drafter", prompt=draft_prompt, result=draft_result)
        draft_text = draft_result.text

        if checker_profile is None:
            # Without a checker there is nothing to approve the draft, so it is handed over as
            # unreviewed rather than being treated as passed.
            checker_passed = False
            break

        checker_prompt = _build_checker_prompt(
            db,
            tenant,
            checker_profile,
            channel=channel,
            draft=draft_text,
            inbound_text=inbound_text,
            plan_instructions=drafter_instruction,
        )
        try:
            checker_result = gemini_client.generate(
                checker_prompt,
                model=checker_profile.model,
                temperature=checker_profile.temperature,
                max_output_tokens=checker_profile.max_output_tokens,
                response_schema=CHECKER_SCHEMA,
            )
        except gemini_client.GeminiClientError as exc:
            recorder.record("checker", prompt=checker_prompt, error=str(exc), model=checker_profile.model)
            recorder.finish(
                STATUS_NEEDS_REVIEW,
                escalation_reason="checker_error",
                final_template_id=template.id,
                final_text=draft_text,
            )
            return PlannerRunResult(
                status=STATUS_NEEDS_REVIEW,
                run_id=run.id,
                generated_text=draft_text,
                template_id=template.id,
                escalation_reason="checker_error",
                attempts=attempt,
            )

        recorder.record("checker", prompt=checker_prompt, result=checker_result)
        verdict = checker_result.parsed or {}
        if verdict.get("passed"):
            checker_passed = True
            feedback = None
            break
        feedback = str(verdict.get("feedback") or "").strip() or "The reviewer rejected the draft."

    if checker_passed:
        recorder.finish(STATUS_COMPLETED, final_template_id=template.id, final_text=draft_text)
        return PlannerRunResult(
            status=STATUS_COMPLETED,
            run_id=run.id,
            generated_text=draft_text,
            template_id=template.id,
            checker_passed=True,
            attempts=run.attempts,
            auto_send_allowed=True,
        )

    # Attempts exhausted (or no checker configured): keep the last draft and park it for a human.
    block_auto_send = checker_profile.block_auto_send_on_fail if checker_profile is not None else True
    recorder.finish(
        STATUS_NEEDS_REVIEW,
        final_template_id=template.id,
        final_text=draft_text,
        checker_feedback=feedback,
        escalation_reason="checker_rejected" if checker_profile is not None else "no_checker_profile",
    )
    return PlannerRunResult(
        status=STATUS_NEEDS_REVIEW,
        run_id=run.id,
        generated_text=draft_text,
        template_id=template.id,
        checker_passed=False,
        checker_feedback=feedback,
        attempts=run.attempts,
        auto_send_allowed=not block_auto_send,
    )
