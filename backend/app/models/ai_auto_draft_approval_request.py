from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class AiAutoDraftApprovalRequest(Base):
    """One row per (draft, notified user): tracks the WhatsApp approval ping sent to a staff
    member for an auto-draft mode AiAutoDraft, and whether/how they responded.

    A draft can have several of these rows (one per opted-in user notified). Whichever row
    gets a `response` first is authoritative - the draft is resolved on that reply, and any
    later reply from another notified user is told who already answered instead of acting
    again.
    """

    __tablename__ = "ai_auto_draft_approval_requests"

    id = Column(Integer, primary_key=True, index=True)
    ai_auto_draft_id = Column(Integer, ForeignKey("ai_auto_drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    phone = Column(String(100), nullable=False)
    external_account_id = Column(String(255), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    responded_at = Column(DateTime(timezone=True), nullable=True)
    response = Column(String(10), nullable=True)  # "YES" / "NO"

    __table_args__ = (
        UniqueConstraint("ai_auto_draft_id", "user_id", name="uq_ai_auto_draft_approval_request_draft_user"),
    )
