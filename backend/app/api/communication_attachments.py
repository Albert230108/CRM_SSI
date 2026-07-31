from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.communication_attachment import CommunicationAttachment
from app.models.gmail_integration import ConversationMessage
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.communication_attachment import StoredAttachmentRead
from app.services.attachment_service import store_upload
from app.services.attachment_storage import (
    AttachmentStorageError,
    AttachmentTooLargeError,
    content_disposition_filename,
    max_file_bytes,
    max_message_bytes,
    read_bytes,
)
from app.services.gmail_attachments import GmailAttachmentNotFoundError, fetch_gmail_attachment_bytes
from app.services.gmail_client import build_gmail_service_for_account

from fastapi import Response

router = APIRouter(prefix="/communications", tags=["communication-attachments"])


class FromGmailAttachmentRequest(BaseModel):
    conversation_message_id: int
    attachment_id: str


def _get_tenant(db: Session, tenant_id: int) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.post(
    "/tenants/{tenant_id}/attachments",
    response_model=list[StoredAttachmentRead],
    status_code=status.HTTP_201_CREATED,
)
async def upload_tenant_attachments(
    tenant_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CommunicationAttachment]:
    tenant = _get_tenant(db, tenant_id)

    per_file_limit = max_file_bytes()
    total_limit = max_message_bytes("whatsapp")  # widest cap; senders re-validate per channel
    total_bytes = 0
    records: list[CommunicationAttachment] = []
    for upload in files:
        data = await upload.read()
        if len(data) > per_file_limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"'{upload.filename}' exceeds the {per_file_limit} byte per-file limit",
            )
        total_bytes += len(data)
        if total_bytes > total_limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Total upload size exceeds the {total_limit} byte limit",
            )
        try:
            record = store_upload(
                db,
                tenant_id=tenant.id,
                filename=upload.filename or "attachment",
                mime_type=upload.content_type,
                data=data,
                user_id=current_user.id,
                origin="upload",
            )
        except AttachmentTooLargeError as exc:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
        records.append(record)
    return records


@router.get("/tenants/{tenant_id}/attachments", response_model=list[StoredAttachmentRead])
async def list_tenant_attachments(
    tenant_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CommunicationAttachment]:
    _get_tenant(db, tenant_id)

    query = db.query(CommunicationAttachment).filter(CommunicationAttachment.tenant_id == tenant_id)
    if q:
        query = query.filter(CommunicationAttachment.filename.ilike(f"%{q}%"))
    return (
        query.order_by(CommunicationAttachment.created_at.desc(), CommunicationAttachment.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/tenants/{tenant_id}/attachments/{attachment_id}/download")
async def download_tenant_attachment(
    tenant_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _get_tenant(db, tenant_id)

    # Tenant scoping (not just "is a CRM user") is the authorization boundary here.
    record = (
        db.query(CommunicationAttachment)
        .filter(CommunicationAttachment.id == attachment_id, CommunicationAttachment.tenant_id == tenant_id)
        .first()
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    try:
        data = read_bytes(record.storage_key)
    except AttachmentStorageError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    safe_filename = content_disposition_filename(record.filename)
    return Response(
        content=data,
        media_type=record.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/tenants/{tenant_id}/attachments/from-gmail",
    response_model=StoredAttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def copy_gmail_attachment_into_storage(
    tenant_id: int,
    payload: FromGmailAttachmentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommunicationAttachment:
    _get_tenant(db, tenant_id)

    message = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.id == payload.conversation_message_id)
        .first()
    )
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    try:
        data, filename, mime_type = fetch_gmail_attachment_bytes(
            db,
            build_service_for_account=build_gmail_service_for_account,
            message=message,
            attachment_id=payload.attachment_id,
        )
    except GmailAttachmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        return store_upload(
            db,
            tenant_id=tenant_id,
            filename=filename,
            mime_type=mime_type,
            data=data,
            user_id=current_user.id,
            origin="gmail",
        )
    except AttachmentTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
