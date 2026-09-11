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
    # True when the sales-manager agent staged a Beds24 invoice-item update for this draft
    # (action="update"): approving/sending this draft pushes that update to Beds24 first.
    has_pending_beds24_update: bool = False
    # The staged Beds24 invoice-item update itself (booking_id, all_original_invoice_item_ids,
    # invoice_items), so the approval UI can show a before/after diff of what will be pushed.
    # None when nothing is staged.
    pending_beds24_update: dict[str, Any] | None = None
    created_at: datetime
