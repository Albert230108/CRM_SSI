from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class FinanceItem(BaseModel):
    id: int | None = None
    type: str
    description: str | None = None
    status: str | None = None
    qty: Decimal = Decimal('1')
    amount: Decimal
    line_total: Decimal
    vat_rate: Decimal = Decimal('0')
    vat_amount: Decimal = Decimal('0')


class Finance(BaseModel):
    charges: list[FinanceItem] = Field(default_factory=list)
    payments: list[FinanceItem] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)
