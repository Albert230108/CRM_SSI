from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentRole = Literal["planner", "checker", "drafter"]
HistoryChannels = Literal["both", "inbound", "email", "whatsapp"]
NoMatchBehaviour = Literal["escalate", "skip"]


class AiAgentProfileBase(BaseModel):
    name: str
    role: AgentRole
    is_default: bool = False
    is_active: bool = True
    instructions: str | None = None
    # Overrides for the fixed prompt scaffolding, keyed by block key. Keys absent from the
    # dict use the built-in default; a key mapped to "" removes that block from the prompt.
    prompt_blocks: dict[str, str] = {}

    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1)

    history_limit: int = Field(default=40, ge=0)
    history_channels: HistoryChannels = "both"
    history_lookback_days: int | None = Field(default=None, ge=1)
    include_beds24: bool = True
    include_payments: bool = False
    include_notes: bool = True
    include_brain_index: bool = True

    match_inbound_language: bool = True
    escalate_keywords: list[str] = []
    on_no_template_match: NoMatchBehaviour = "escalate"
    min_confidence: float = Field(default=0.5, ge=0, le=1)

    max_redraft_attempts: int = Field(default=2, ge=0, le=5)
    block_auto_send_on_fail: bool = True

    daily_token_cap: int | None = Field(default=None, ge=1)

    # `model` collides with pydantic's protected namespace; the field is a Gemini model id.
    model_config = ConfigDict(protected_namespaces=())


class AiAgentProfileCreate(AiAgentProfileBase):
    pass


class AiAgentProfileUpdate(AiAgentProfileBase):
    pass


class AiAgentProfileRead(AiAgentProfileBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
