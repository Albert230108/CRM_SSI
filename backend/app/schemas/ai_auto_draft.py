from datetime import datetime

from pydantic import BaseModel


class AiAutoDraftRead(BaseModel):
    id: int
    tenant_id: int
    tenant_name: str | None = None
    # The email thread this draft answers (a Conversation id), and the tenant that currently has
    # that thread visible/active - the two values the UI needs to deep-link "Open thread" to the
    # right tenant and thread even when the draft's stored tenant later hid it. Both null for
    # WhatsApp drafts.
    email_thread_id: int | None = None
    open_thread_tenant_id: int | None = None
    channel: str
    template_id: int | None = None
    generated_text: str
    formatted_text: str | None = None
    quoted_context: str | None = None
    status: str
    scheduled_send_at: datetime | None = None
    created_at: datetime
