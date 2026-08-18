from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AiReplyTemplateSection(BaseModel):
    label: str
    content: str
    # Canvas-only metadata: not read by the prompt builder. id/x/y/order may be absent for
    # sections created before the canvas editor existed.
    id: str | None = None
    x: float | None = None
    y: float | None = None
    order: int | None = None


class AiReplyTemplateNote(BaseModel):
    """A freeform post-it note on the section canvas. Never sent to the AI."""

    id: str
    text: str
    x: float
    y: float
    color: str | None = None


class AiReplyTemplateCreate(BaseModel):
    name: str
    # Free-text explanation of when to use this template. Read by the Planner, not the drafter.
    description: str | None = None
    guidelines: str | None = None
    sections: list[AiReplyTemplateSection] = []
    canvas_notes: list[AiReplyTemplateNote] = []
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
    canvas_notes: list[AiReplyTemplateNote] = []
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
    canvas_notes: list[AiReplyTemplateNote] = []
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
