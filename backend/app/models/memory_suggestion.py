from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func

from app.database import Base

KIND_FIELD_VALUE = "field_value"
KIND_BRAIN_ENTRY = "brain_entry"
KIND_RULE_ADD = "rule_add"
KIND_RULE_MODIFY = "rule_modify"
KIND_RULE_DELETE = "rule_delete"
KIND_ACTION_ITEM_MODIFY = "action_item_modify"
KIND_ACTION_ITEM_DELETE = "action_item_delete"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class MemorySuggestion(Base):
    """An AI-proposed change to a tenant's working memory, a global rule, or an action item.
    Rule/field/entry kinds arise from a redo's "what"/"why" feedback (see memory_redo_service);
    action_item_modify/delete arise from the action writer agent (see action_writer_service)
    deciding an *existing* item needs to change - new items it creates directly, no approval
    needed. Always requires human approval - see memory_suggestion_service for what applying
    each kind actually does. tenant_id is null for rule kinds, since rules are global; set for
    action_item kinds, since action items are tenant-scoped. target_id points at the row being
    modified/deleted (field_definition_id for field_value, working_memory_rule id for
    rule_modify/rule_delete, action_item id for action_item_modify/delete); null for anything new.
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
