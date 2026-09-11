from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_agent_profile import AiAgentProfile
from app.models.user import User
from app.schemas.ai_agent_profile import AiAgentProfileCreate, AiAgentProfileRead, AiAgentProfileUpdate
from app.services import ai_prompt_blocks
from app.services.ai_agent_instructions import build_instructions_text

router = APIRouter(prefix="/ai-agent-profiles", tags=["ai-agent-profiles"])

# instructions / instruction_sections / instruction_canvas_notes are handled separately by
# _apply_instructions - they need conditional derivation, not a blind copy.
_ASSIGNABLE_FIELDS = (
    "name",
    "role",
    "is_active",
    "prompt_blocks",
    "model",
    "temperature",
    "max_output_tokens",
    "redo_model",
    "redo_temperature",
    "redo_max_output_tokens",
    "history_limit",
    "history_channels",
    "history_lookback_days",
    "include_beds24",
    "include_payments",
    "include_notes",
    "include_availability",
    "include_tenant_brain",
    "include_brain_index",
    "always_include_brain_sections",
    "match_inbound_language",
    "escalate_keywords",
    "on_no_template_match",
    "min_confidence",
    "max_redraft_attempts",
    "block_auto_send_on_fail",
    "daily_token_cap",
)


def _get_profile(db: Session, profile_id: int) -> AiAgentProfile:
    profile = db.query(AiAgentProfile).filter(AiAgentProfile.id == profile_id).first()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent profile not found")
    return profile


def _apply_instructions(profile: AiAgentProfile, payload: AiAgentProfileCreate | AiAgentProfileUpdate) -> None:
    """Whichever editing mode is active on this save writes both representations.

    Grid mode (instruction_sections is a list, even empty): the cards are authoritative -
    `instructions` is derived from them server-side, keeping every existing reader of that column
    unchanged. Classic mode (instruction_sections omitted/None): the submitted `instructions` is
    authoritative and gets mirrored into a single card, so switching back to the grid later shows
    the full text on one card rather than losing it.
    """
    if payload.instruction_sections is not None:
        sections = [section.model_dump() for section in payload.instruction_sections]
        profile.instruction_sections = sections
        profile.instruction_canvas_notes = (
            [note.model_dump() for note in payload.instruction_canvas_notes]
            if payload.instruction_canvas_notes is not None
            else []
        )
        profile.instructions = build_instructions_text(sections)
    else:
        text = (payload.instructions or "").strip()
        profile.instructions = payload.instructions
        profile.instruction_sections = [{"id": None, "label": "", "content": text, "order": 0}] if text else []
        profile.instruction_canvas_notes = []


def _apply_default_flag(db: Session, profile: AiAgentProfile, is_default: bool) -> None:
    """Keep at most one default per role, so profile resolution is never ambiguous."""
    if not is_default:
        profile.is_default = False
        return
    db.query(AiAgentProfile).filter(
        AiAgentProfile.role == profile.role, AiAgentProfile.id != profile.id
    ).update({AiAgentProfile.is_default: False}, synchronize_session=False)
    profile.is_default = True


class PromptBlockDefinition(BaseModel):
    """One editable piece of an agent's prompt scaffolding, as the settings UI renders it."""

    key: str
    label: str
    help: str
    default: str
    group: str


@router.get("/prompt-blocks", response_model=list[PromptBlockDefinition])
def list_prompt_blocks(
    role: str = Query(..., pattern="^(planner|checker|drafter|brain_writer|action_writer|formatter|sales_manager|memory_redo|memory_qa|run_qa)$"),
    current_user: User = Depends(get_current_user),
) -> list[PromptBlockDefinition]:
    """The blocks a profile of this role may override, with their built-in default text.

    Serving the registry rather than duplicating it in TypeScript is what lets the form render
    the real defaults and offer a per-field "reset" without the two copies drifting apart.
    """
    return [
        PromptBlockDefinition(
            key=block.key, label=block.label, help=block.help, default=block.default, group=block.group
        )
        for block in ai_prompt_blocks.BLOCKS_BY_ROLE[role]
    ]


@router.get("", response_model=list[AiAgentProfileRead])
def list_agent_profiles(
    role: str | None = Query(None, pattern="^(planner|checker|drafter|brain_writer|action_writer|formatter|sales_manager|memory_redo|memory_qa|run_qa)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AiAgentProfile]:
    query = db.query(AiAgentProfile)
    if role is not None:
        query = query.filter(AiAgentProfile.role == role)
    return query.order_by(AiAgentProfile.role, AiAgentProfile.name).all()


# Ordered agent metadata for the overview map. Kept here (not in TypeScript) so the diagram and
# the profile editor never disagree about which roles exist or what they do.
_AGENT_META: tuple[dict, ...] = (
    {"role": "planner", "label": "Planner", "description": "Reads the conversation, picks a template and channel, and decides whether the sales manager is needed."},
    {"role": "sales_manager", "label": "Sales Manager", "description": "Prices a stay and, when asked, renders a PDF quotation via the quotation manager, then hands the figures to the drafter."},
    {"role": "drafter", "label": "Drafter", "description": "Writes the actual reply text from the planner's instruction and any quote."},
    {"role": "checker", "label": "Checker", "description": "Proof-reads the draft; approves it or sends it back to the drafter to redraft."},
    {"role": "formatter", "label": "Formatter", "description": "Reformats an approved reply into channel-specific output (HTML for email, markdown for WhatsApp)."},
    {"role": "brain_writer", "label": "Brain Writer", "description": "Independently decides what about a tenant is worth remembering long-term."},
    {"role": "action_writer", "label": "Action Writer", "description": "Independently proposes or creates tenant action items."},
)

# Which pin column on TenantAiSettings counts as "tenants using this role's chosen profile".
_ROLE_PIN_COLUMN = {
    "planner": "planner_profile_id",
    "checker": "checker_profile_id",
    "drafter": "drafter_profile_id",
    "formatter": "formatter_profile_id",
    "sales_manager": "sales_manager_profile_id",
    "brain_writer": "brain_writer_profile_id",
    "action_writer": "action_writer_profile_id",
}

# Context toggles on a profile -> the external/CRM node the diagram links that agent to.
_CONTEXT_TO_EXTERNAL = {
    "include_beds24": "beds24",
    "include_availability": "beds24",
    "include_payments": "payments",
    "include_notes": "notes",
    "include_tenant_brain": "brain",
    "include_brain_index": "brain",
}


@router.get("/graph")
def get_agent_graph(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """A data-driven map of the agents, how they connect, and their CRM/external links.

    The topology (which stage feeds which) is fixed, but every node is annotated with live
    config - how many active profiles a role has, whether it has a default, how many tenants pin
    it, and which external systems its active profiles actually read - so the diagram reflects the
    real deployment rather than a hand-drawn ideal.
    """
    from sqlalchemy import func

    from app.models.tenant_ai_settings import TenantAiSettings

    profiles = db.query(AiAgentProfile).all()
    by_role: dict[str, list[AiAgentProfile]] = {}
    for profile in profiles:
        by_role.setdefault(profile.role, []).append(profile)

    agents = []
    for meta in _AGENT_META:
        role = meta["role"]
        role_profiles = by_role.get(role, [])
        active = [p for p in role_profiles if p.is_active]
        context_keys: set[str] = set()
        for profile in active:
            for flag, external in _CONTEXT_TO_EXTERNAL.items():
                if getattr(profile, flag, False):
                    context_keys.add(external)

        tenants_pinned = 0
        pin_column = _ROLE_PIN_COLUMN.get(role)
        if pin_column is not None:
            tenants_pinned = (
                db.query(func.count(TenantAiSettings.tenant_id))
                .filter(getattr(TenantAiSettings, pin_column).isnot(None))
                .scalar()
                or 0
            )

        agents.append(
            {
                "role": role,
                "label": meta["label"],
                "description": meta["description"],
                "active_profiles": len(active),
                "total_profiles": len(role_profiles),
                "has_default": any(p.is_default and p.is_active for p in role_profiles),
                "tenants_pinned": tenants_pinned,
                "reads": sorted(context_keys),
            }
        )

    externals = [
        {"key": "email", "label": "Email (Gmail)", "kind": "channel"},
        {"key": "whatsapp", "label": "WhatsApp", "kind": "channel"},
        {"key": "beds24", "label": "Beds24", "kind": "external"},
        {"key": "quotation_manager", "label": "Quotation Manager / OneDrive", "kind": "external"},
        {"key": "brain", "label": "Tenant Brain", "kind": "crm"},
        {"key": "notes", "label": "Notes", "kind": "crm"},
        {"key": "payments", "label": "Payments", "kind": "crm"},
        {"key": "templates", "label": "Reply Templates", "kind": "crm"},
    ]

    # Structural pipeline + integration edges. `kind` lets the frontend style each class of arrow.
    edges = [
        {"from": "email", "to": "planner", "label": "inbound", "kind": "trigger"},
        {"from": "whatsapp", "to": "planner", "label": "inbound", "kind": "trigger"},
        {"from": "planner", "to": "sales_manager", "label": "if quote needed", "kind": "flow"},
        {"from": "planner", "to": "drafter", "label": "instruction", "kind": "flow"},
        {"from": "sales_manager", "to": "drafter", "label": "prices", "kind": "flow"},
        {"from": "sales_manager", "to": "quotation_manager", "label": "price + PDF", "kind": "integration"},
        {"from": "planner", "to": "templates", "label": "picks template", "kind": "integration"},
        {"from": "drafter", "to": "checker", "label": "draft", "kind": "flow"},
        {"from": "checker", "to": "drafter", "label": "redraft", "kind": "loop"},
        {"from": "checker", "to": "formatter", "label": "approved", "kind": "flow"},
        {"from": "formatter", "to": "email", "label": "send", "kind": "send"},
        {"from": "formatter", "to": "whatsapp", "label": "send", "kind": "send"},
        {"from": "quotation_manager", "to": "email", "label": "PDF attached", "kind": "send"},
        {"from": "quotation_manager", "to": "whatsapp", "label": "PDF attached", "kind": "send"},
        {"from": "email", "to": "brain_writer", "label": "inbound", "kind": "trigger"},
        {"from": "whatsapp", "to": "brain_writer", "label": "inbound", "kind": "trigger"},
        {"from": "email", "to": "action_writer", "label": "inbound", "kind": "trigger"},
        {"from": "whatsapp", "to": "action_writer", "label": "inbound", "kind": "trigger"},
    ]
    # Live context edges: an agent -> external only when some active profile actually reads it.
    for agent in agents:
        for external in agent["reads"]:
            edges.append({"from": agent["role"], "to": external, "label": "reads", "kind": "context"})

    return {"agents": agents, "externals": externals, "edges": edges}


@router.get("/{profile_id}", response_model=AiAgentProfileRead)
def get_agent_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAgentProfile:
    return _get_profile(db, profile_id)


@router.post("", response_model=AiAgentProfileRead, status_code=status.HTTP_201_CREATED)
def create_agent_profile(
    payload: AiAgentProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAgentProfile:
    profile = AiAgentProfile(
        **{field: getattr(payload, field) for field in _ASSIGNABLE_FIELDS},
        created_by_user_id=current_user.id,
    )
    profile.name = profile.name.strip()
    _apply_instructions(profile, payload)
    db.add(profile)
    db.flush()
    _apply_default_flag(db, profile, payload.is_default)
    db.commit()
    db.refresh(profile)
    return profile


@router.put("/{profile_id}", response_model=AiAgentProfileRead)
def update_agent_profile(
    profile_id: int,
    payload: AiAgentProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiAgentProfile:
    profile = _get_profile(db, profile_id)
    for field in _ASSIGNABLE_FIELDS:
        setattr(profile, field, getattr(payload, field))
    profile.name = profile.name.strip()
    _apply_instructions(profile, payload)
    _apply_default_flag(db, profile, payload.is_default)
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    profile = _get_profile(db, profile_id)
    if profile.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This is the default profile for its role. Make another profile the default first.",
        )
    db.delete(profile)
    db.commit()
