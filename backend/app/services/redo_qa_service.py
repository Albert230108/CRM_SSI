"""Answers questions about one specific redo request log, grounded in the full redo context."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.ai_agent_profile import MEMORY_REDO_ROLE, AiAgentProfile
from app.models.ai_agent_run import STATUS_COMPLETED, STATUS_FAILED, AiAgentRun, AiAgentRunStep
from app.models.redo_request_log import RedoRequestLog
from app.models.redo_qa_message import ROLE_ASSISTANT, ROLE_USER, RedoQaMessage
from app.services import ai_agent_orchestrator, ai_prompt_blocks, gemini_client, memory_redo_service

_PREAMBLE = (
    "You are answering a staff member's questions about one specific redo-agent run in a short-stay rental CRM. "
    "Use only the context provided below, and say plainly when the context does not support an answer instead of guessing."
)

_QA_HISTORY_LIMIT = 10


@dataclass
class _QaRunRecorder:
    """Keeps the QA-chat run log aligned with the planner run accounting model."""

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

    def finish(self, status: str) -> None:
        self.run.status = status
        self.run.duration_ms = int((time.monotonic() - self.started) * 1000)


def _resolved_profile_and_blocks(db: Session) -> tuple[AiAgentProfile | None, dict[str, str]]:
    profile = ai_agent_orchestrator.resolve_profile(db, MEMORY_REDO_ROLE, None)
    return profile, ai_prompt_blocks.resolve_blocks(profile, MEMORY_REDO_ROLE)


def _run_log_text(db: Session, blocks: dict[str, str], redo_log: RedoRequestLog) -> str:
    if redo_log.ai_agent_run_id is None:
        return ""
    return memory_redo_service._run_log_block(db, blocks, redo_log.ai_agent_run_id)


def build_context_parts(db: Session, redo_log: RedoRequestLog) -> dict[str, str]:
    profile, blocks = _resolved_profile_and_blocks(db)
    instructions = (profile.instructions or "").strip() if profile is not None else ""
    run_log_text = _run_log_text(db, blocks, redo_log)
    return {
        "what": redo_log.what,
        "why": redo_log.why or "",
        "instructions": instructions,
        "run_log_text": run_log_text,
        "context_text": build_context_text(db, redo_log, profile=profile, blocks=blocks),
    }


def get_context(db: Session, redo_log: RedoRequestLog) -> dict[str, str]:
    parts = build_context_parts(db, redo_log)
    return {
        "what": parts["what"],
        "why": parts["why"],
        "instructions": parts["instructions"],
        "run_log_text": parts["run_log_text"],
    }


def build_context_text(
    db: Session,
    redo_log: RedoRequestLog,
    *,
    profile: AiAgentProfile | None = None,
    blocks: dict[str, str] | None = None,
) -> str:
    profile = profile if profile is not None else ai_agent_orchestrator.resolve_profile(db, MEMORY_REDO_ROLE, None)
    blocks = blocks if blocks is not None else ai_prompt_blocks.resolve_blocks(profile, MEMORY_REDO_ROLE)

    parts: list[str] = []
    redo_lines = [f"What to change: {redo_log.what}"]
    if redo_log.why:
        redo_lines.append(f"Why: {redo_log.why}")
    parts.append(ai_prompt_blocks.join(blocks["ctx_redo"], "\n".join(redo_lines)))

    instructions = (profile.instructions or "").strip() if profile is not None else ""
    if instructions:
        parts.append(ai_prompt_blocks.join(blocks["instructions_header"], instructions))

    run_log_text = _run_log_text(db, blocks, redo_log)
    if run_log_text:
        parts.append(run_log_text)

    return "\n\n".join(part for part in parts if part.strip())


def _qa_history_block(history: list[RedoQaMessage], blocks: dict[str, str]) -> str:
    if not history:
        return ""
    lines = [f"{'Staff' if m.role == ROLE_USER else 'Assistant'}: {m.content}" for m in history[-_QA_HISTORY_LIMIT:]]
    return ai_prompt_blocks.join(blocks["ctx_history"], "\n".join(lines))


def list_history(db: Session, redo_request_log_id: int, limit: int = 50) -> list[RedoQaMessage]:
    return (
        db.query(RedoQaMessage)
        .filter(RedoQaMessage.redo_request_log_id == redo_request_log_id)
        .order_by(RedoQaMessage.created_at.asc(), RedoQaMessage.id.asc())
        .limit(limit)
        .all()
    )


def answer_question(db: Session, redo_log: RedoRequestLog, question: str, asked_by_user_id: int | None = None) -> RedoQaMessage:
    question = (question or "").strip()
    profile = ai_agent_orchestrator.resolve_profile(db, MEMORY_REDO_ROLE, None)
    blocks = ai_prompt_blocks.resolve_blocks(profile, MEMORY_REDO_ROLE)
    history = list_history(db, redo_log.id)
    run = AiAgentRun(
        tenant_id=redo_log.tenant_id,
        channel="qa",
        mode="manual",
        status=STATUS_FAILED,
        created_by_user_id=asked_by_user_id,
    )
    db.add(run)
    db.flush()
    recorder = _QaRunRecorder(run=run, db=db)

    context_text = build_context_text(db, redo_log, profile=profile, blocks=blocks)
    parts: list[str] = [_PREAMBLE]
    if context_text.strip():
        parts.append(context_text)

    history_block = _qa_history_block(history, blocks)
    if history_block:
        parts.append(history_block)

    parts.append(ai_prompt_blocks.join(blocks["ctx_question"], question))
    prompt = "\n\n".join(part for part in parts if part.strip())

    try:
        result = gemini_client.generate(
            prompt,
            model=profile.model if profile is not None else None,
            temperature=profile.temperature if profile is not None else None,
            max_output_tokens=profile.max_output_tokens if profile is not None else None,
        )
        answer_text = result.text
        recorder.record("qa", prompt=prompt, result=result)
        recorder.finish(STATUS_COMPLETED)
    except gemini_client.GeminiClientError as exc:
        answer_text = "Sorry, I couldn't answer that right now - please try again."
        recorder.record(
            "qa",
            prompt=prompt,
            error=str(exc),
            model=profile.model if profile is not None else None,
        )
        recorder.finish(STATUS_FAILED)

    db.add(RedoQaMessage(redo_request_log_id=redo_log.id, role=ROLE_USER, content=question, asked_by_user_id=asked_by_user_id))
    assistant_message = RedoQaMessage(
        redo_request_log_id=redo_log.id,
        ai_agent_run_id=run.id,
        role=ROLE_ASSISTANT,
        content=answer_text,
    )
    db.add(assistant_message)
    db.flush()
    return assistant_message
