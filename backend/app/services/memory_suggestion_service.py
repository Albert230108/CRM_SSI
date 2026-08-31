"""Applying an approved MemorySuggestion - see memory_redo_service for how suggestions are
proposed. Every kind re-checks its target before applying, since a suggestion can sit pending
for a while during which the target might be edited or removed by someone else.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.action_item import STATUS_OPEN as ACTION_ITEM_STATUS_OPEN
from app.models.action_item import ActionItem
from app.models.ai_agent_profile import AiAgentProfile
from app.models.ai_reply_template import AiReplyTemplate
from app.models.brain_field_definition import BrainFieldDefinition
from app.models.memory_suggestion import (
    KIND_ACTION_ITEM_COMPLETE,
    KIND_ACTION_ITEM_DELETE,
    KIND_ACTION_ITEM_MODIFY,
    KIND_BRAIN_ENTRY,
    KIND_FIELD_VALUE,
    KIND_PROFILE_CHANGE,
    KIND_RULE_ADD,
    KIND_RULE_DELETE,
    KIND_RULE_MODIFY,
    KIND_TEMPLATE_CHANGE,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    MemorySuggestion,
)
from app.models.tenant import Tenant
from app.models.working_memory_rule import SOURCE_AI_SUGGESTED, STATUS_ACTIVE, WorkingMemoryRule
from app.services import action_item_service, brain_field_service, tenant_brain_service, working_memory_rule_service


_ACTION_ITEM_KINDS = {KIND_ACTION_ITEM_MODIFY, KIND_ACTION_ITEM_DELETE, KIND_ACTION_ITEM_COMPLETE}


def list_pending(db: Session, *, exclude_kinds: set[str] | None = None) -> list[MemorySuggestion]:
    """Rule/field/entry suggestions. Action-item modify/delete/complete suggestions have their own
    dedicated review surface (see list_pending_action_item_suggestions and the Actions page) -
    the caller excludes those kinds here so they don't show up twice."""
    query = db.query(MemorySuggestion).filter(MemorySuggestion.status == STATUS_PENDING)
    if exclude_kinds:
        query = query.filter(MemorySuggestion.kind.notin_(exclude_kinds))
    return query.order_by(MemorySuggestion.created_at.desc()).all()


def list_pending_action_item_suggestions(db: Session) -> list[MemorySuggestion]:
    return (
        db.query(MemorySuggestion)
        .filter(MemorySuggestion.status == STATUS_PENDING, MemorySuggestion.kind.in_(_ACTION_ITEM_KINDS))
        .order_by(MemorySuggestion.created_at.desc())
        .all()
    )


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    message: str


def _apply_field_value(db: Session, suggestion: MemorySuggestion, reviewer_id: int | None) -> ApplyResult:
    definition = db.query(BrainFieldDefinition).filter(BrainFieldDefinition.id == suggestion.target_id).first()
    if definition is None or not definition.is_active:
        return ApplyResult(False, "The target field no longer exists or was deactivated.")
    brain_field_service.set_value(
        db, suggestion.tenant_id, definition.id, suggestion.proposed_value.get("value"), source="planner", updated_by_user_id=reviewer_id
    )
    return ApplyResult(True, "Field value updated.")


def _apply_brain_entry(db: Session, suggestion: MemorySuggestion, reviewer_id: int | None) -> ApplyResult:
    tenant = db.query(Tenant).filter(Tenant.id == suggestion.tenant_id).first()
    if tenant is None:
        return ApplyResult(False, "The tenant no longer exists.")
    tenant_brain_service.add_entry(db, tenant, suggestion.proposed_value.get("content", ""), source="planner", changed_by_user_id=reviewer_id)
    return ApplyResult(True, "Brain entry added.")


def _apply_rule_add(db: Session, suggestion: MemorySuggestion, reviewer_id: int | None) -> ApplyResult:
    rule = working_memory_rule_service.add_rule(
        db,
        suggestion.proposed_value.get("condition_text", ""),
        suggestion.proposed_value.get("action_text", ""),
        source=SOURCE_AI_SUGGESTED,
        status=STATUS_ACTIVE,
        created_by_user_id=reviewer_id,
    )
    if rule is None:
        return ApplyResult(False, "The proposed rule was missing a condition or action.")
    return ApplyResult(True, "Rule created.")


def _apply_rule_modify(db: Session, suggestion: MemorySuggestion) -> ApplyResult:
    rule = db.query(WorkingMemoryRule).filter(WorkingMemoryRule.id == suggestion.target_id).first()
    if rule is None or rule.status == "dismissed":
        return ApplyResult(False, "The target rule no longer exists or was already dismissed.")
    working_memory_rule_service.update_rule(
        db, rule, condition_text=suggestion.proposed_value.get("condition_text"), action_text=suggestion.proposed_value.get("action_text")
    )
    return ApplyResult(True, "Rule updated.")


def _apply_rule_delete(db: Session, suggestion: MemorySuggestion) -> ApplyResult:
    rule = db.query(WorkingMemoryRule).filter(WorkingMemoryRule.id == suggestion.target_id).first()
    if rule is None or rule.status == "dismissed":
        return ApplyResult(False, "The target rule no longer exists or was already dismissed.")
    working_memory_rule_service.dismiss_rule(db, rule)
    return ApplyResult(True, "Rule dismissed.")


def _apply_profile_change(db: Session, suggestion: MemorySuggestion) -> ApplyResult:
    """Suggestion-only: approving records that a human reviewed and accepted this recommendation.
    It never rewrites the profile itself - a human edits it by hand in the Agent Profiles editor,
    since profile instructions/prompt overrides are too consequential to auto-rewrite from a
    redo's guess.
    """
    profile = db.query(AiAgentProfile).filter(AiAgentProfile.id == suggestion.target_id).first()
    if profile is None:
        return ApplyResult(False, "The target agent profile no longer exists.")
    return ApplyResult(True, "Reviewed. Edit this agent profile manually to apply the suggested change.")


def _apply_template_change(db: Session, suggestion: MemorySuggestion) -> ApplyResult:
    """Suggestion-only, same reasoning as _apply_profile_change but for reply templates."""
    template = db.query(AiReplyTemplate).filter(AiReplyTemplate.id == suggestion.target_id).first()
    if template is None:
        return ApplyResult(False, "The target reply template no longer exists.")
    section_id = (suggestion.proposed_value or {}).get("section_id")
    if section_id:
        section_label = next(
            (s.get("label") for s in (template.sections or []) if isinstance(s, dict) and s.get("id") == section_id),
            None,
        )
        if section_label:
            return ApplyResult(True, f"Reviewed. Edit this reply template's '{section_label}' section manually to apply the suggested change.")
    return ApplyResult(True, "Reviewed. Edit this reply template manually to apply the suggested change.")


def _apply_action_item_modify(db: Session, suggestion: MemorySuggestion) -> ApplyResult:
    item = db.query(ActionItem).filter(ActionItem.id == suggestion.target_id).first()
    if item is None or item.status != ACTION_ITEM_STATUS_OPEN:
        return ApplyResult(False, "The target action item no longer exists or is no longer open.")
    proposed = suggestion.proposed_value or {}
    due_date_raw = proposed.get("due_date")
    due_date = None
    if due_date_raw:
        try:
            due_date = date.fromisoformat(str(due_date_raw))
        except ValueError:
            due_date = None
    action_item_service.update(
        db,
        item,
        title=proposed.get("title"),
        ai_instruction=proposed.get("ai_instruction"),
        due_date=due_date,
        tag_ids=proposed.get("tag_ids"),
        priority=proposed.get("priority"),
    )
    return ApplyResult(True, "Action item updated.")


def _apply_action_item_delete(db: Session, suggestion: MemorySuggestion) -> ApplyResult:
    item = db.query(ActionItem).filter(ActionItem.id == suggestion.target_id).first()
    if item is None or item.status != ACTION_ITEM_STATUS_OPEN:
        return ApplyResult(False, "The target action item no longer exists or is no longer open.")
    action_item_service.dismiss(db, item)
    return ApplyResult(True, "Action item dismissed.")


def _apply_action_item_complete(db: Session, suggestion: MemorySuggestion) -> ApplyResult:
    item = db.query(ActionItem).filter(ActionItem.id == suggestion.target_id).first()
    if item is None or item.status != ACTION_ITEM_STATUS_OPEN:
        return ApplyResult(False, "The target action item no longer exists or is no longer open.")
    action_item_service.complete(db, item)
    return ApplyResult(True, "Action item completed.")


def approve(db: Session, suggestion: MemorySuggestion, reviewer_id: int | None = None) -> ApplyResult:
    if suggestion.status != STATUS_PENDING:
        return ApplyResult(False, "This suggestion has already been reviewed.")

    handlers = {
        KIND_FIELD_VALUE: lambda: _apply_field_value(db, suggestion, reviewer_id),
        KIND_BRAIN_ENTRY: lambda: _apply_brain_entry(db, suggestion, reviewer_id),
        KIND_RULE_ADD: lambda: _apply_rule_add(db, suggestion, reviewer_id),
        KIND_RULE_MODIFY: lambda: _apply_rule_modify(db, suggestion),
        KIND_RULE_DELETE: lambda: _apply_rule_delete(db, suggestion),
        KIND_PROFILE_CHANGE: lambda: _apply_profile_change(db, suggestion),
        KIND_TEMPLATE_CHANGE: lambda: _apply_template_change(db, suggestion),
        KIND_ACTION_ITEM_MODIFY: lambda: _apply_action_item_modify(db, suggestion),
        KIND_ACTION_ITEM_DELETE: lambda: _apply_action_item_delete(db, suggestion),
        KIND_ACTION_ITEM_COMPLETE: lambda: _apply_action_item_complete(db, suggestion),
    }
    handler = handlers.get(suggestion.kind)
    result = handler() if handler is not None else ApplyResult(False, "Unknown suggestion kind.")

    suggestion.status = STATUS_APPROVED if result.applied else STATUS_REJECTED
    suggestion.reviewed_by_user_id = reviewer_id
    suggestion.reviewed_at = datetime.now(timezone.utc)
    return result


def reject(db: Session, suggestion: MemorySuggestion, reviewer_id: int | None = None) -> None:
    suggestion.status = STATUS_REJECTED
    suggestion.reviewed_by_user_id = reviewer_id
    suggestion.reviewed_at = datetime.now(timezone.utc)
