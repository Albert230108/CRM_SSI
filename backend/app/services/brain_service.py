"""The Brain: one global knowledge tree that AI templates reference instead of duplicating.

Two reference styles are supported and both land in the same rendered text:
  * inline  - a `{{brain:policies.cancellation}}` token anywhere in a template's guidelines or
              section content, expanded in place;
  * attached - an explicit list of sections linked to the template, rendered as their own
              "Knowledge Base" prompt block.

Note the token syntax deliberately contains `:` and `.`, neither of which is matched by
`email_template_service._PLACEHOLDER_PATTERN` (`\\w+`), so brain tokens survive tenant
placeholder resolution untouched and the two systems never fight over the same text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.brain_section import BrainSection

# Brain content may itself reference other sections. Expansion is bounded so a mistaken
# reference cycle degrades to truncated text rather than hanging a request.
MAX_TOKEN_DEPTH = 3

_BRAIN_TOKEN_PATTERN = re.compile(r"\{\{\s*brain:([A-Za-z0-9_.\-]+)\s*\}\}")

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class BrainSectionError(ValueError):
    """Raised for invalid tree operations (bad slug, cycle, unknown parent)."""


@dataclass
class BrainResolution:
    """Rendered text plus the paths that could not be resolved, so callers can warn the author."""

    text: str
    missing_paths: list[str] = field(default_factory=list)


def validate_slug(slug: str) -> str:
    cleaned = (slug or "").strip().lower()
    if not _SLUG_PATTERN.match(cleaned):
        raise BrainSectionError(
            "Slug must be lowercase letters, digits and single hyphens (e.g. 'late-check-in')."
        )
    return cleaned


def slugify(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return lowered or "section"


def compute_path(parent: BrainSection | None, slug: str) -> str:
    return f"{parent.path}.{slug}" if parent is not None else slug


def get_by_path(db: Session, path: str) -> BrainSection | None:
    return db.query(BrainSection).filter(BrainSection.path == path).first()


def is_descendant(candidate: BrainSection, ancestor: BrainSection) -> bool:
    """True when `candidate` sits inside `ancestor`'s subtree (or is `ancestor` itself)."""
    return candidate.id == ancestor.id or candidate.path.startswith(f"{ancestor.path}.")


def reindex_subtree(db: Session, node: BrainSection) -> None:
    """Recompute `path` for `node` and every descendant after a rename or reparent.

    Paths are matched by prefix, so this must run inside the same transaction as the change
    that invalidated them - otherwise `{{brain:...}}` tokens resolve against stale paths.
    """
    old_path = node.path
    # Read the parent by id rather than through the relationship: on a reparent the caller has
    # just assigned parent_id and the loaded `parent` object may still be the previous one.
    parent = (
        db.query(BrainSection).filter(BrainSection.id == node.parent_id).first()
        if node.parent_id is not None
        else None
    )
    new_path = compute_path(parent, node.slug)
    if old_path == new_path:
        return

    # Slugs cannot contain `_`, so no LIKE wildcard escaping is needed here.
    descendants = db.query(BrainSection).filter(BrainSection.path.like(f"{old_path}.%")).all()
    node.path = new_path
    for descendant in descendants:
        descendant.path = new_path + descendant.path[len(old_path) :]


def next_position(db: Session, parent_id: int | None) -> int:
    siblings = db.query(BrainSection).filter(BrainSection.parent_id == parent_id).all()
    return max((sibling.position for sibling in siblings), default=-1) + 1


def _sorted_children(db: Session, node: BrainSection) -> list[BrainSection]:
    return (
        db.query(BrainSection)
        .filter(BrainSection.parent_id == node.id, BrainSection.is_active.is_(True))
        .order_by(BrainSection.position, BrainSection.id)
        .all()
    )


def render_section(
    db: Session,
    path: str,
    *,
    include_descendants: bool = True,
    heading_level: int = 2,
) -> str | None:
    """Render one node (and by default its subtree) as markdown headings + content.

    Returns None when the path is unknown or the node is inactive, so the caller can decide
    between silently dropping the reference and warning about it.
    """
    node = get_by_path(db, path)
    if node is None or not node.is_active:
        return None
    return _render_node(db, node, include_descendants=include_descendants, heading_level=heading_level)


def _render_node(db: Session, node: BrainSection, *, include_descendants: bool, heading_level: int) -> str:
    hashes = "#" * min(heading_level, 6)
    blocks = [f"{hashes} {node.title}"]
    content = (node.content or "").strip()
    if content:
        blocks.append(content)
    if include_descendants:
        for child in _sorted_children(db, node):
            blocks.append(
                _render_node(db, child, include_descendants=True, heading_level=heading_level + 1)
            )
    return "\n".join(blocks)


def resolve_brain_tokens(db: Session, text: str) -> BrainResolution:
    """Expand every `{{brain:path}}` token in `text`, including tokens inside brain content."""
    missing: list[str] = []
    resolved = _expand(db, text or "", depth=0, visited=frozenset(), missing=missing)
    # Preserve first-seen order while dropping repeats of the same bad path.
    unique_missing = list(dict.fromkeys(missing))
    return BrainResolution(text=resolved, missing_paths=unique_missing)


def _expand(db: Session, text: str, *, depth: int, visited: frozenset[str], missing: list[str]) -> str:
    if depth >= MAX_TOKEN_DEPTH:
        # Strip any remaining tokens rather than emitting raw syntax into the prompt.
        return _BRAIN_TOKEN_PATTERN.sub("", text)

    def _replace(match: re.Match[str]) -> str:
        path = match.group(1)
        if path in visited:
            return ""
        rendered = render_section(db, path)
        if rendered is None:
            missing.append(path)
            return ""
        return _expand(db, rendered, depth=depth + 1, visited=visited | {path}, missing=missing)

    return _BRAIN_TOKEN_PATTERN.sub(_replace, text)


def referenced_paths(text: str) -> list[str]:
    """Every brain path a piece of template text mentions, in first-seen order."""
    return list(dict.fromkeys(_BRAIN_TOKEN_PATTERN.findall(text or "")))


def render_paths(db: Session, paths: list[str]) -> BrainResolution:
    """Render an explicit list of paths as one block, de-duplicated and order-preserving."""
    missing: list[str] = []
    blocks: list[str] = []
    for path in dict.fromkeys(paths):
        rendered = render_section(db, path)
        if rendered is None:
            missing.append(path)
            continue
        blocks.append(_expand(db, rendered, depth=1, visited=frozenset({path}), missing=missing))
    return BrainResolution(text="\n\n".join(block for block in blocks if block.strip()), missing_paths=missing)


def build_brain_index(db: Session) -> str:
    """A compact table of contents given to the Planner so it knows what knowledge exists."""
    nodes = (
        db.query(BrainSection)
        .filter(BrainSection.is_active.is_(True))
        .order_by(BrainSection.path)
        .all()
    )
    if not nodes:
        return "No brain sections defined."
    return "\n".join(f"- {node.path} — {node.title}" for node in nodes)
