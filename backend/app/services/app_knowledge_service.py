"""CRUD and search over the "how the CRM works" knowledge base.

This is the living document the user and the assistant grow together: a staff member can add or
edit an entry directly, and the assistant may *suggest* one after answering a question that
wasn't already covered (see ai_assistant_service.py) - a human always saves it. Search is a
plain case-insensitive substring match over title/body, matching the portable ILIKE approach in
search_service.py rather than adding a new index/dependency for what is currently a small corpus.
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.app_knowledge_entry import SOURCE_AI, SOURCE_USER, AppKnowledgeEntry

DEFAULT_SEARCH_LIMIT = 5


def list_entries(db: Session) -> list[AppKnowledgeEntry]:
    return db.query(AppKnowledgeEntry).order_by(AppKnowledgeEntry.title).all()


def get_entry(db: Session, entry_id: int) -> AppKnowledgeEntry | None:
    return db.query(AppKnowledgeEntry).filter(AppKnowledgeEntry.id == entry_id).first()


def search(db: Session, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[AppKnowledgeEntry]:
    term = (query or "").strip()
    if not term:
        return []
    like = f"%{term}%"
    return (
        db.query(AppKnowledgeEntry)
        .filter(or_(AppKnowledgeEntry.title.ilike(like), AppKnowledgeEntry.body.ilike(like)))
        .order_by(AppKnowledgeEntry.updated_at.desc())
        .limit(limit)
        .all()
    )


def create_entry(
    db: Session,
    *,
    title: str,
    body: str,
    category: str | None = None,
    source: str = SOURCE_USER,
    created_by_user_id: int | None = None,
) -> AppKnowledgeEntry:
    entry = AppKnowledgeEntry(
        title=title.strip(),
        body=body.strip(),
        category=(category or "").strip() or None,
        source=source if source in (SOURCE_USER, SOURCE_AI) else SOURCE_USER,
        created_by_user_id=created_by_user_id,
    )
    db.add(entry)
    db.flush()
    return entry


def update_entry(
    db: Session,
    entry: AppKnowledgeEntry,
    *,
    title: str | None = None,
    body: str | None = None,
    category: str | None = None,
) -> AppKnowledgeEntry:
    if title is not None:
        entry.title = title.strip()
    if body is not None:
        entry.body = body.strip()
    if category is not None:
        entry.category = category.strip() or None
    db.flush()
    return entry


def delete_entry(db: Session, entry: AppKnowledgeEntry) -> None:
    db.delete(entry)
