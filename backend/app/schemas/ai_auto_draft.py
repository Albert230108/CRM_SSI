from datetime import datetime
from typing import Any

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
    # True when the sales manager prepared a Beds24 write for this draft (an invoice-item update
    # or a brand-new booking): approving/sending this draft runs it past the executor agent, which
    # pushes it to Beds24 first if approved.
    has_pending_execution: bool = False
    # The prepared Beds24 write itself (action + booking_id/invoice_items, or
    # action="create"+create_payload), so the approval UI can show a before/after diff of what
    # will be pushed. None when nothing is prepared.
    pending_execution: dict[str, Any] | None = None
    # Lifecycle of the prepared Beds24 write, tracked separately from `status` so the UI can show
    # (and independently approve) the Beds24 action in its own column: None | "pending" |
    # "executed" | "rejected" | "failed". See AiAutoDraft.execution_status.
    execution_status: str | None = None
    # True when a quotation PDF (by path or, for older drafts, by stored attachment) is attached
    # to this draft.
    has_quotation: bool = False
    quotation_filename: str | None = None
    created_at: datetime
