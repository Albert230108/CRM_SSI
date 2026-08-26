from sqlalchemy import Column, DateTime, Integer, Numeric, String, func

from app.database import Base


class AiModelPricing(Base):
    """Cost rates for a model name, used to turn stored token counts into a $ figure."""

    __tablename__ = "ai_model_pricing"

    id = Column(Integer, primary_key=True, index=True)
    model = Column(String(120), nullable=False, unique=True, index=True)
    input_cost_per_million_tokens = Column(Numeric(10, 4), nullable=False, default=0, server_default="0")
    output_cost_per_million_tokens = Column(Numeric(10, 4), nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
