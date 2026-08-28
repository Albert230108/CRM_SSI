from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_agent_profile import AiAgentProfile
from app.models.user import User
from app.schemas.ai_agent_profile import AiAgentProfileCreate, AiAgentProfileRead, AiAgentProfileUpdate
from app.services import ai_prompt_blocks

router = APIRouter(prefix="/ai-agent-profiles", tags=["ai-agent-profiles"])

_ASSIGNABLE_FIELDS = (
    "name",
    "role",
    "is_active",
    "instructions",
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
    role: str = Query(..., pattern="^(planner|checker|drafter|brain_writer|action_writer|formatter|memory_redo|memory_qa)$"),
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
    role: str | None = Query(None, pattern="^(planner|checker|drafter|brain_writer|action_writer|formatter|memory_redo|memory_qa)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AiAgentProfile]:
    query = db.query(AiAgentProfile)
    if role is not None:
        query = query.filter(AiAgentProfile.role == role)
    return query.order_by(AiAgentProfile.role, AiAgentProfile.name).all()


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
