from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AiReplyTemplateSection(BaseModel):
    label: str
    content: str


class AiReplyTemplateCreate(BaseModel):
    name: str
    # Free-text explanation of when to use this template. Read by the Planner, not the drafter.
    description: str | None = None
    guidelines: str | None = None
    sections: list[AiReplyTemplateSection] = []
    brain_section_ids: list[int] = []
    include_history: bool = False
    history_message_limit: int | None = None
    include_beds24: bool = False
    include_payments: bool = False
    include_notes: bool = False


class AiReplyTemplateUpdate(BaseModel):
    name: str
    description: str | None = None
    guidelines: str | None = None
    sections: list[AiReplyTemplateSection] = []
    brain_section_ids: list[int] = []
    include_history: bool = False
    history_message_limit: int | None = None
    include_beds24: bool = False
    include_payments: bool = False
    include_notes: bool = False


class AiReplyTemplateRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    guidelines: str | None = None
    sections: list[AiReplyTemplateSection]
    brain_section_ids: list[int] = []
    include_history: bool
    history_message_limit: int | None = None
    include_beds24: bool
    include_payments: bool
    include_notes: bool
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
