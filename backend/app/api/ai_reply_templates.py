from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.ai_reply_template import AiReplyTemplate
from app.models.user import User
from app.schemas.ai_reply_template import AiReplyTemplateCreate, AiReplyTemplateRead, AiReplyTemplateUpdate

router = APIRouter(prefix="/ai-reply-templates", tags=["ai-reply-templates"])


def _get_template(db: Session, template_id: int) -> AiReplyTemplate:
    template = db.query(AiReplyTemplate).filter(AiReplyTemplate.id == template_id).first()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template


@router.get("", response_model=list[AiReplyTemplateRead])
def list_ai_reply_templates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[AiReplyTemplate]:
    return db.query(AiReplyTemplate).order_by(AiReplyTemplate.name).all()


@router.post("", response_model=AiReplyTemplateRead, status_code=status.HTTP_201_CREATED)
def create_ai_reply_template(
    payload: AiReplyTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiReplyTemplate:
    template = AiReplyTemplate(
        name=payload.name.strip(),
        sections=[section.model_dump() for section in payload.sections],
        include_history=payload.include_history,
        history_message_limit=payload.history_message_limit,
        include_beds24=payload.include_beds24,
        include_payments=payload.include_payments,
        include_notes=payload.include_notes,
        created_by_user_id=current_user.id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.put("/{template_id}", response_model=AiReplyTemplateRead)
def update_ai_reply_template(
    template_id: int,
    payload: AiReplyTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiReplyTemplate:
    template = _get_template(db, template_id)
    template.name = payload.name.strip()
    template.sections = [section.model_dump() for section in payload.sections]
    template.include_history = payload.include_history
    template.history_message_limit = payload.history_message_limit
    template.include_beds24 = payload.include_beds24
    template.include_payments = payload.include_payments
    template.include_notes = payload.include_notes
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_reply_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    template = _get_template(db, template_id)
    db.delete(template)
    db.commit()
