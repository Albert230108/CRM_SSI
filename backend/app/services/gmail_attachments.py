import base64

from sqlalchemy.orm import Session

from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount


class GmailAttachmentNotFoundError(Exception):
    pass


def fetch_gmail_attachment_bytes(
    db: Session, *, build_service_for_account, message: ConversationMessage, attachment_id: str
) -> tuple[bytes, str, str]:
    """Fetch an inbound Gmail attachment's bytes, filename, and mime type.

    build_service_for_account is injected (rather than imported) to avoid a new
    app.api -> app.api import; app/api/gmail_integration.py passes its own
    _build_service_for_account.
    """
    raw_payload = message.raw_payload if isinstance(message.raw_payload, dict) else {}
    attachments = raw_payload.get("attachments") or []
    attachment_meta = next((item for item in attachments if item.get("attachment_id") == attachment_id), None)
    if attachment_meta is None:
        raise GmailAttachmentNotFoundError("Attachment not found on this message")

    conversation = db.query(Conversation).filter(Conversation.id == message.conversation_id).first()
    if conversation is None or conversation.provider_account_id is None:
        raise GmailAttachmentNotFoundError("Gmail account not found for message")
    account = db.query(GmailAccount).filter(GmailAccount.id == conversation.provider_account_id).first()
    if account is None:
        raise GmailAttachmentNotFoundError("Gmail account not found for message")

    service = build_service_for_account(account)
    result = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message.provider_message_id, id=attachment_id)
        .execute()
    )
    data = base64.urlsafe_b64decode(result["data"].encode("utf-8"))
    filename = attachment_meta.get("filename") or "attachment"
    mime_type = attachment_meta.get("mime_type") or "application/octet-stream"
    return data, filename, mime_type
