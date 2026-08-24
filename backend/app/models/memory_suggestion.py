from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func

from app.database import Base

KIND_FIELD_VALUE = "field_value"
KIND_BRAIN_ENTRY = "brain_entry"
KIND_RULE_ADD = "rule_add"
KIND_RULE_MODIFY = "rule_modify"
KIND_RULE_DELETE = "rule_delete"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class MemorySuggestion(Base):
    """An AI-proposed change to a tenant's working memory or a global rule, arising from a
    redo's "what"/"why" feedback. Always requires human approval - see memory_suggestion_service
    for what applying each kind actually does. tenant_id is null for rule kinds, since rules are
    global. target_id points at the row being modified/deleted (field_definition_id for
    field_value, working_memory_rule id for rule_modify/rule_delete); null for anything new.
    """

    __tablename__ = "memory_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    target_id = Column(Integer, nullable=True)
    proposed_value = Column(JSON, nullable=False)
    reasoning = Column(Text, nullable=True)
    source_redo_log_id = Column(Integer, ForeignKey("redo_request_logs.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, default=STATUS_PENDING, server_default=STATUS_PENDING)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
