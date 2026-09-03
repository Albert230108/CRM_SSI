"""Answers questions about one specific AI agent run, grounded in that run's full step log.

This is the run-debug twin of `redo_qa_service`: the redo chat is keyed on a redo log, while this
chat is keyed directly on the `AiAgentRun` being inspected, so the same chat explains a planner,
brain-writer, or action-writer run without any per-type code.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.ai_agent_profile import RUN_QA_ROLE, AiAgentProfile
from app.models.ai_agent_run import STATUS_COMPLETED, STATUS_FAILED, AiAgentRun, AiAgentRunStep
from app.models.run_qa_message import ROLE_ASSISTANT, ROLE_USER, RunQaMessage
from app.services import ai_agent_orchestrator, ai_prompt_blocks, gemini_client, memory_redo_service

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
    profile = ai_agent_orchestrator.resolve_profile(db, RUN_QA_ROLE, None)
    return profile, ai_prompt_blocks.resolve_blocks(profile, RUN_QA_ROLE)


def _run_summary_text(run: AiAgentRun) -> str:
    return (
        f"run_id={run.id} tenant_id={run.tenant_id} mode={run.mode} channel={run.channel} "
        f"status={run.status} final_template_id={run.final_template_id} "
        f"tokens={run.total_prompt_tokens + run.total_output_tokens}"
    )


def _run_log_text(db: Session, blocks: dict[str, str], run: AiAgentRun) -> str:
    return memory_redo_service._run_log_block(db, blocks, run.id)


def build_context_parts(db: Session, run: AiAgentRun) -> dict[str, str | float | int | None]:
    profile, blocks = _resolved_profile_and_blocks(db)
    instructions = (profile.instructions or "").strip() if profile is not None else ""
    return {
        "run_summary": _run_summary_text(run),
        "instructions": instructions,
        "qa_preamble": blocks["qa_preamble"],
        "model": profile.model if profile is not None and profile.model else gemini_client.GEMINI_MODEL,
        "temperature": profile.temperature if profile is not None else None,
        "max_output_tokens": profile.max_output_tokens if profile is not None else None,
        "run_log_text": _run_log_text(db, blocks, run),
        "context_text": build_context_text(db, run, profile=profile, blocks=blocks),
    }


def get_context(db: Session, run: AiAgentRun) -> dict[str, str | float | int | None]:
    parts = build_context_parts(db, run)
    return {
        "run_summary": parts["run_summary"],
        "instructions": parts["instructions"],
        "qa_preamble": parts["qa_preamble"],
        "model": parts["model"],
        "temperature": parts["temperature"],
        "max_output_tokens": parts["max_output_tokens"],
        "run_log_text": parts["run_log_text"],
    }


def build_context_text(
    db: Session,
    run: AiAgentRun,
    *,
    profile: AiAgentProfile | None = None,
    blocks: dict[str, str] | None = None,
) -> str:
    profile = profile if profile is not None else ai_agent_orchestrator.resolve_profile(db, RUN_QA_ROLE, None)
    blocks = blocks if blocks is not None else ai_prompt_blocks.resolve_blocks(profile, RUN_QA_ROLE)

    parts: list[str] = [ai_prompt_blocks.join(blocks["ctx_run_summary"], _run_summary_text(run))]

    instructions = (profile.instructions or "").strip() if profile is not None else ""
    if instructions:
        parts.append(ai_prompt_blocks.join(blocks["instructions_header"], instructions))

    run_log_text = _run_log_text(db, blocks, run)
    if run_log_text:
        parts.append(run_log_text)

    return "\n\n".join(part for part in parts if part.strip())


def _qa_history_block(history: list[RunQaMessage], blocks: dict[str, str]) -> str:
    if not history:
        return ""
    lines = [f"{'Staff' if m.role == ROLE_USER else 'Assistant'}: {m.content}" for m in history[-_QA_HISTORY_LIMIT:]]
    return ai_prompt_blocks.join(blocks["ctx_history"], "\n".join(lines))


def list_history(db: Session, agent_run_id: int, limit: int = 50) -> list[RunQaMessage]:
    return (
        db.query(RunQaMessage)
        .filter(RunQaMessage.agent_run_id == agent_run_id)
        .order_by(RunQaMessage.created_at.asc(), RunQaMessage.id.asc())
        .limit(limit)
        .all()
    )


def answer_question(db: Session, subject_run: AiAgentRun, question: str, asked_by_user_id: int | None = None) -> RunQaMessage:
    question = (question or "").strip()
    profile = ai_agent_orchestrator.resolve_profile(db, RUN_QA_ROLE, None)
    blocks = ai_prompt_blocks.resolve_blocks(profile, RUN_QA_ROLE)
    history = list_history(db, subject_run.id)
    run = AiAgentRun(
        tenant_id=subject_run.tenant_id,
        channel="qa",
        mode="manual",
        status=STATUS_FAILED,
        created_by_user_id=asked_by_user_id,
    )
    db.add(run)
    db.flush()
    recorder = _QaRunRecorder(run=run, db=db)

    context_text = build_context_text(db, subject_run, profile=profile, blocks=blocks)
    parts: list[str] = [blocks["qa_preamble"]]
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

    db.add(RunQaMessage(agent_run_id=subject_run.id, role=ROLE_USER, content=question, asked_by_user_id=asked_by_user_id))
    assistant_message = RunQaMessage(
        agent_run_id=subject_run.id,
        qa_run_id=run.id,
        role=ROLE_ASSISTANT,
        content=answer_text,
    )
    db.add(assistant_message)
    db.flush()
    return assistant_message
