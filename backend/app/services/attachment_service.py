from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.communication_attachment import CommunicationAttachment, CommunicationAttachmentLink
from app.services.attachment_storage import (
    AttachmentStorageError,
    guess_mime,
    max_file_bytes,
    max_message_bytes,
    read_bytes,
    save_bytes,
)


class AttachmentNotFoundError(Exception):
    pass


class AttachmentLimitExceededError(Exception):
    pass


@dataclass(frozen=True)
class OutboundAttachment:
    attachment_id: int
    filename: str
    mime_type: str
    content: bytes


def store_upload(
    db: Session,
    *,
    tenant_id: int,
    filename: str,
    mime_type: str | None,
    data: bytes,
    user_id: int | None,
    origin: str,
) -> CommunicationAttachment:
    blob = save_bytes(tenant_id, data, filename)

    existing = (
        db.query(CommunicationAttachment)
        .filter(
            CommunicationAttachment.tenant_id == tenant_id,
            CommunicationAttachment.sha256 == blob.sha256,
        )
        .first()
    )
    if existing is not None:
        return existing

    record = CommunicationAttachment(
        tenant_id=tenant_id,
        storage_key=blob.storage_key,
        filename=filename or "attachment",
        mime_type=guess_mime(filename, mime_type),
        size_bytes=blob.size_bytes,
        sha256=blob.sha256,
        origin=origin,
        uploaded_by_user_id=user_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def load_outbound_attachments(
    db: Session, *, tenant_id: int, attachment_ids: list[int], channel: str
) -> list[OutboundAttachment]:
    if not attachment_ids:
        return []

    records = (
        db.query(CommunicationAttachment)
        .filter(
            CommunicationAttachment.tenant_id == tenant_id,
            CommunicationAttachment.id.in_(attachment_ids),
        )
        .all()
    )
    by_id = {record.id: record for record in records}
    missing = [aid for aid in attachment_ids if aid not in by_id]
    if missing:
        raise AttachmentNotFoundError(f"Attachment(s) not found for this tenant: {missing}")

    total_bytes = sum(by_id[aid].size_bytes for aid in attachment_ids)
    if total_bytes > max_message_bytes(channel):
        raise AttachmentLimitExceededError(
            f"Total attachment size {total_bytes} bytes exceeds the {max_message_bytes(channel)} byte limit"
        )

    result: list[OutboundAttachment] = []
    for aid in attachment_ids:
        record = by_id[aid]
        try:
            content = read_bytes(record.storage_key)
        except AttachmentStorageError as exc:
            raise AttachmentNotFoundError(str(exc)) from exc
        result.append(
            OutboundAttachment(
                attachment_id=record.id,
                filename=record.filename,
                mime_type=record.mime_type or "application/octet-stream",
                content=content,
            )
        )
    return result


def link_attachments(
    db: Session,
    *,
    attachment_ids: list[int],
    communication_id: int | None = None,
    conversation_message_id: int | None = None,
) -> None:
    for position, attachment_id in enumerate(attachment_ids):
        db.add(
            CommunicationAttachmentLink(
                attachment_id=attachment_id,
                communication_id=communication_id,
                conversation_message_id=conversation_message_id,
                position=position,
            )
        )
    db.commit()


def _bulk_attachments_by_link_column(db: Session, column, ids: list[int]) -> dict[int, list[CommunicationAttachment]]:
    if not ids:
        return {}

    rows = (
        db.query(CommunicationAttachmentLink, CommunicationAttachment)
        .join(CommunicationAttachment, CommunicationAttachmentLink.attachment_id == CommunicationAttachment.id)
        .filter(column.in_(ids))
        .order_by(CommunicationAttachmentLink.position)
        .all()
    )
    result: dict[int, list[CommunicationAttachment]] = {}
    for link, attachment in rows:
        key = getattr(link, column.key)
        result.setdefault(key, []).append(attachment)
    return result


def attachments_for_communications(db: Session, communication_ids: list[int]) -> dict[int, list[CommunicationAttachment]]:
    return _bulk_attachments_by_link_column(db, CommunicationAttachmentLink.communication_id, communication_ids)


def attachments_for_conversation_messages(
    db: Session, conversation_message_ids: list[int]
) -> dict[int, list[CommunicationAttachment]]:
    return _bulk_attachments_by_link_column(
        db, CommunicationAttachmentLink.conversation_message_id, conversation_message_ids
    )


def max_file_bytes_limit() -> int:
    return max_file_bytes()
