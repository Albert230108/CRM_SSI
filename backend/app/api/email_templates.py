from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.email_template import EmailTemplate
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.email_template import (
    EmailTemplateCreate,
    EmailTemplatePreviewRequest,
    EmailTemplatePreviewResponse,
    EmailTemplateRead,
    EmailTemplateUpdate,
)
from app.services.email_template_service import resolve_template_text

router = APIRouter(prefix="/email-templates", tags=["email-templates"])


def _get_owned_template(db: Session, template_id: int, current_user: User) -> EmailTemplate:
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if template.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
    return template


@router.get("", response_model=list[EmailTemplateRead])
def list_email_templates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[EmailTemplate]:
    return db.query(EmailTemplate).filter(EmailTemplate.user_id == current_user.id).order_by(EmailTemplate.name).all()


@router.post("", response_model=EmailTemplateRead, status_code=status.HTTP_201_CREATED)
def create_email_template(
    payload: EmailTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmailTemplate:
    template = EmailTemplate(
        user_id=current_user.id,
        name=payload.name.strip(),
        subject=payload.subject.strip() if payload.subject else None,
        body=payload.body,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.put("/{template_id}", response_model=EmailTemplateRead)
def update_email_template(
    template_id: int,
    payload: EmailTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmailTemplate:
    template = _get_owned_template(db, template_id, current_user)
    template.name = payload.name.strip()
    template.subject = payload.subject.strip() if payload.subject else None
    template.body = payload.body
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_email_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    template = _get_owned_template(db, template_id, current_user)
    db.delete(template)
    db.commit()


@router.post("/{template_id}/preview", response_model=EmailTemplatePreviewResponse)
def preview_email_template(
    template_id: int,
    payload: EmailTemplatePreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmailTemplatePreviewResponse:
    template = _get_owned_template(db, template_id, current_user)
    tenant = db.query(Tenant).filter(Tenant.id == payload.tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    resolved_subject = resolve_template_text(template.subject, tenant) if template.subject else None
    resolved_body = resolve_template_text(template.body, tenant)
    return EmailTemplatePreviewResponse(subject=resolved_subject, body=resolved_body)
