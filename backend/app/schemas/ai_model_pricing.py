from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AiModelPricingRead(BaseModel):
    id: int
    model: str
    input_cost_per_million_tokens: float
    output_cost_per_million_tokens: float
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AiModelPricingUpsert(BaseModel):
    """Create-or-update by model name; used for both add-new-row and edit-existing-row."""

    model: str = Field(min_length=1, max_length=120)
    input_cost_per_million_tokens: float = Field(ge=0)
    output_cost_per_million_tokens: float = Field(ge=0)


class AiModelPricingListRead(BaseModel):
    items: list[AiModelPricingRead]
