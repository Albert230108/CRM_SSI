from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.services import search_service

router = APIRouter(prefix="/search", tags=["search"])


class SearchResult(BaseModel):
    type: str
    id: int
    tenant_id: Optional[int] = None
    title: str
    snippet: str


@router.get("", response_model=list[SearchResult])
def global_search(
    q: str,
    types: Annotated[list[str] | None, Query()] = None,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SearchResult]:
    """Search across every text-bearing entity in the CRM.

    ``types`` optionally restricts the search to the given result types (the frontend filter
    chips); ``limit`` caps results per type so no single entity dominates.
    """
    hits = search_service.search(db, q, types=types, per_type_limit=limit)
    return [
        SearchResult(type=h.type, id=h.id, tenant_id=h.tenant_id, title=h.title, snippet=h.snippet)
        for h in hits
    ]
