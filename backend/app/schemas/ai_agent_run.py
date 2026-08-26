from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AiAgentRunStepRead(BaseModel):
    id: int
    step_index: int
    stage: str
    model: str | None = None
    prompt: str | None = None
    response: str | None = None
    parsed: Any | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class AiAgentRunRead(BaseModel):
    id: int
    tenant_id: int
    tenant_name: str | None = None
    channel: str
    mode: str
    display_mode: str = ""
    status: str
    escalation_reason: str | None = None
    planner_profile_id: int | None = None
    checker_profile_id: int | None = None
    final_template_id: int | None = None
    final_template_name: str | None = None
    checker_feedback: str | None = None
    attempts: int
    total_prompt_tokens: int
    total_output_tokens: int
    total_cost: float | None = None
    pricing_missing: bool = False
    duration_ms: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AiAgentRunDetail(AiAgentRunRead):
    final_text: str | None = None
    steps: list[AiAgentRunStepRead] = []
    # Names for every template id referenced anywhere in this run - the final choice and any
    # alternatives the planner considered and rejected - keyed by id for the frontend to look up.
    template_names: dict[int, str] = {}


class AiAgentRunListRead(BaseModel):
    items: list[AiAgentRunRead]
    total: int


class AiModelUsageStat(BaseModel):
    model: str
    prompt_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost: float | None = None
    output_cost: float | None = None
    total_cost: float | None = None
    pricing_missing: bool = False


class AiAgentRunStatsRead(BaseModel):
    period: str
    total_runs: int
    total_prompt_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost: float | None = None
    any_pricing_missing: bool = False
    by_model: list[AiModelUsageStat] = Field(default_factory=list)
