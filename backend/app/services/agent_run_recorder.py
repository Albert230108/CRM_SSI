"""Shared helper that appends model-call steps to an AiAgentRun and keeps its accounting.

Extracted from run_qa_service so the floating copilot can log its chats into the same
AiAgentRun log the planner pipeline uses. It works for a brand-new run (step index starts at 0)
and for a run that already has steps (a continuing assistant conversation), where the index
picks up after the existing steps instead of colliding with them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ai_agent_run import AiAgentRun, AiAgentRunStep
from app.services import gemini_client


@dataclass
class AgentRunRecorder:
    """Keeps a run's step log and token/duration accounting aligned as calls are recorded."""

    run: AiAgentRun
    db: Session
    started: float = field(default_factory=time.monotonic)
    _index: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        # Continue after any steps the run already has, so an assistant conversation that asks a
        # second question appends rather than overwrites. A fresh run has no steps, so this is 0.
        existing = (
            self.db.query(func.count(AiAgentRunStep.id))
            .filter(AiAgentRunStep.run_id == self.run.id)
            .scalar()
        )
        self._index = int(existing or 0)

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
        # Accumulate so a multi-question conversation reflects total time spent, not just the
        # last turn. A fresh run starts at the default 0.
        self.run.duration_ms = (self.run.duration_ms or 0) + int((time.monotonic() - self.started) * 1000)
