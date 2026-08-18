from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_reply_template import AiReplyTemplate, AiReplyTemplateBrainSection
from app.models.brain_section import BrainSection
from app.models.user import User
from app.schemas.brain_section import (
    BrainSectionCreate,
    BrainSectionMove,
    BrainSectionNode,
    BrainSectionRead,
    BrainSectionUpdate,
)
from app.services import brain_service

router = APIRouter(prefix="/brain-sections", tags=["brain-sections"])


def _get_section(db: Session, section_id: int) -> BrainSection:
    section = db.query(BrainSection).filter(BrainSection.id == section_id).first()
    if section is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brain section not found")
    return section


def _build_tree(sections: list[BrainSection]) -> list[BrainSectionNode]:
    """Serialise the roots; nesting comes from the model's `children` relationship, which is
    already ordered by (position, id), so no manual assembly is needed."""
    return [BrainSectionNode.model_validate(section) for section in sections if section.parent_id is None]


def _referencing_templates(db: Session, paths: list[str]) -> list[str]:
    """Templates that would break if these paths disappeared - inline tokens or attached links."""
    names: list[str] = []
    for template in db.query(AiReplyTemplate).all():
        haystack = [template.guidelines or ""]
        haystack += [str(section.get("content") or "") for section in (template.sections or [])]
        mentioned = {path for text in haystack for path in brain_service.referenced_paths(text)}
        if mentioned & set(paths):
            names.append(template.name)
    linked = (
        db.query(AiReplyTemplate.name)
        .join(AiReplyTemplateBrainSection, AiReplyTemplateBrainSection.template_id == AiReplyTemplate.id)
        .join(BrainSection, BrainSection.id == AiReplyTemplateBrainSection.brain_section_id)
        .filter(BrainSection.path.in_(paths))
        .all()
    )
    names += [row[0] for row in linked]
    return sorted(set(names))


@router.get("", response_model=list[BrainSectionNode])
def list_brain_sections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BrainSectionNode]:
    sections = db.query(BrainSection).order_by(BrainSection.position, BrainSection.id).all()
    return _build_tree(sections)


@router.get("/flat", response_model=list[BrainSectionRead])
def list_brain_sections_flat(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BrainSection]:
    return db.query(BrainSection).order_by(BrainSection.path).all()


@router.post("", response_model=BrainSectionRead, status_code=status.HTTP_201_CREATED)
def create_brain_section(
    payload: BrainSectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BrainSection:
    parent = _get_section(db, payload.parent_id) if payload.parent_id is not None else None
    try:
        slug = brain_service.validate_slug(payload.slug or brain_service.slugify(payload.title))
    except brain_service.BrainSectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    path = brain_service.compute_path(parent, slug)
    if brain_service.get_by_path(db, path) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"A section already exists at '{path}'."
        )

    section = BrainSection(
        parent_id=parent.id if parent else None,
        slug=slug,
        path=path,
        title=payload.title.strip(),
        content=(payload.content or "").strip() or None,
        position=brain_service.next_position(db, parent.id if parent else None),
        is_active=payload.is_active,
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    return section


@router.put("/{section_id}", response_model=BrainSectionRead)
def update_brain_section(
    section_id: int,
    payload: BrainSectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BrainSection:
    section = _get_section(db, section_id)
    try:
        slug = brain_service.validate_slug(payload.slug or section.slug)
    except brain_service.BrainSectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if slug != section.slug:
        new_path = brain_service.compute_path(section.parent, slug)
        existing = brain_service.get_by_path(db, new_path)
        if existing is not None and existing.id != section.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=f"A section already exists at '{new_path}'."
            )

    section.title = payload.title.strip()
    section.content = (payload.content or "").strip() or None
    section.is_active = payload.is_active
    section.slug = slug
    section.updated_by_user_id = current_user.id
    brain_service.reindex_subtree(db, section)
    db.commit()
    db.refresh(section)
    return section


@router.post("/{section_id}/move", response_model=BrainSectionRead)
def move_brain_section(
    section_id: int,
    payload: BrainSectionMove,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BrainSection:
    section = _get_section(db, section_id)
    parent = _get_section(db, payload.parent_id) if payload.parent_id is not None else None
    if parent is not None and brain_service.is_descendant(parent, section):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A section cannot be moved inside itself or one of its own descendants.",
        )

    new_path = brain_service.compute_path(parent, section.slug)
    existing = brain_service.get_by_path(db, new_path)
    if existing is not None and existing.id != section.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"A section already exists at '{new_path}'."
        )

    section.parent_id = parent.id if parent else None
    section.position = payload.position
    section.updated_by_user_id = current_user.id
    brain_service.reindex_subtree(db, section)

    # Renumber the destination siblings so positions stay dense and the requested slot wins.
    siblings = (
        db.query(BrainSection)
        .filter(BrainSection.parent_id == section.parent_id, BrainSection.id != section.id)
        .order_by(BrainSection.position, BrainSection.id)
        .all()
    )
    ordered = siblings[: payload.position] + [section] + siblings[payload.position :]
    for index, sibling in enumerate(ordered):
        sibling.position = index

    db.commit()
    db.refresh(section)
    return section


@router.delete("/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brain_section(
    section_id: int,
    cascade: bool = Query(False, description="Required when the section has children."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    section = _get_section(db, section_id)
    subtree = (
        db.query(BrainSection)
        .filter((BrainSection.id == section.id) | (BrainSection.path.like(f"{section.path}.%")))
        .all()
    )
    if len(subtree) > 1 and not cascade:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{section.path}' has {len(subtree) - 1} child section(s). Re-send with cascade=true.",
        )

    referencing = _referencing_templates(db, [node.path for node in subtree])
    if referencing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Still referenced by template(s): " + ", ".join(referencing),
        )

    db.delete(section)
    db.commit()
