import base64
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.communication import Communication
from app.models.gmail_integration import GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_email_address import TenantEmailAddress

if TYPE_CHECKING:
    from app.services.attachment_service import OutboundAttachment

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]


def decrypt_refresh_token(encrypted_refresh_token: str | None) -> str | None:
    if not encrypted_refresh_token:
        return None
    try:
        key = os.getenv("GMAIL_TOKEN_ENCRYPTION_KEY")
        if not key:
            return None
        cipher = Fernet(key.encode("utf-8"))
        return cipher.decrypt(encrypted_refresh_token.encode("utf-8")).decode("utf-8")
    except Exception:
        return None


def build_gmail_credentials(account: GmailAccount) -> Credentials | None:
    refresh_token = decrypt_refresh_token(account.refresh_token_encrypted)
    if not refresh_token:
        return None
    try:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=account.token_uri or "https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
            scopes=account.scopes_json or GMAIL_SCOPES,
        )
        # Refresh the token to get a valid access token
        credentials.refresh(GoogleAuthRequest())
        return credentials
    except Exception:
        return None


def _build_service(credentials_info: dict[str, Any]) -> Any:
    credentials = Credentials.from_authorized_user_info(credentials_info, scopes=GMAIL_SCOPES)
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def build_gmail_service_for_account(account: GmailAccount) -> Any:
    credentials = build_gmail_credentials(account)
    if credentials is None:
        raise ValueError("Gmail account credentials are missing or could not be decrypted")
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _parse_internal_date(value: str | int | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def _extract_message_text(payload: dict[str, Any]) -> str:
    body = payload.get("body") or {}
    data = body.get("data")
    if data:
        return base64.urlsafe_b64decode(data.encode('utf-8')).decode('utf-8', errors='ignore')
    parts = payload.get("parts") or []
    texts: list[str] = []
    for part in parts:
        mime_type = part.get("mimeType")
        part_body = part.get("body") or {}
        if mime_type == "text/plain" and part_body.get("data"):
            texts.append(base64.urlsafe_b64decode(part_body["data"].encode('utf-8')).decode('utf-8', errors='ignore'))
    return "\n".join(texts)


def _find_tenant(db: Session, headers: list[dict[str, Any]]) -> Tenant | None:
    email = None
    for header in headers:
        if str(header.get("name", "")).lower() == "from":
            value = str(header.get("value") or "")
            email = value.split("<")[-1].rstrip(">").strip() if "@" in value else value.strip()
            break
    if not email:
        return None
    # CRM_EMAIL links only - Tenant.email is no longer an authoritative address.
    linked = (
        db.query(TenantEmailAddress)
        .filter(func.lower(TenantEmailAddress.email) == email.strip().lower(), TenantEmailAddress.is_active.is_(True))
        .first()
    )
    if linked is not None:
        return db.query(Tenant).filter(Tenant.id == linked.tenant_id).first()
    return None


def _send_gmail_message(
    credentials: Credentials,
    *,
    thread_id: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    from_email: str,
    subject_prefix: str,
    in_reply_to_message_id: str | None = None,
    references: str | None = None,
    attachments: Sequence["OutboundAttachment"] = (),
) -> dict[str, Any]:
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    message = EmailMessage()
    message["To"] = to_email
    message["From"] = from_email
    if not subject.lower().startswith(subject_prefix.lower()):
        subject = f"{subject_prefix} {subject}"
    message["Subject"] = subject
    if in_reply_to_message_id:
        message["In-Reply-To"] = in_reply_to_message_id
    if references:
        message["References"] = references
    message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype="html")

    # add_attachment promotes the message to multipart/mixed on the first call, so a send
    # with no attachments produces exactly the same single-part bytes it always did.
    for item in attachments:
        maintype, _, subtype = (item.mime_type or "application/octet-stream").partition("/")
        message.add_attachment(
            item.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=item.filename,
        )

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw_message, "threadId": thread_id},
    ).execute()
    return result


def send_gmail_reply(
    credentials: Credentials,
    *,
    thread_id: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    from_email: str,
    in_reply_to_message_id: str | None = None,
    references: str | None = None,
    attachments: Sequence["OutboundAttachment"] = (),
) -> dict[str, Any]:
    return _send_gmail_message(
        credentials,
        thread_id=thread_id,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        from_email=from_email,
        subject_prefix="Re:",
        in_reply_to_message_id=in_reply_to_message_id,
        references=references,
        attachments=attachments,
    )


def send_gmail_forward(
    credentials: Credentials,
    *,
    thread_id: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    from_email: str,
    in_reply_to_message_id: str | None = None,
    references: str | None = None,
    attachments: Sequence["OutboundAttachment"] = (),
) -> dict[str, Any]:
    return _send_gmail_message(
        credentials,
        thread_id=thread_id,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        from_email=from_email,
        subject_prefix="Fwd:",
        in_reply_to_message_id=in_reply_to_message_id,
        references=references,
        attachments=attachments,
    )


def list_thread_drafts(credentials: Credentials, thread_id: str) -> list[dict[str, Any]]:
    """List Gmail drafts belonging to the given thread. Used to retrieve an externally
    AI-authored draft reply so a user can review/edit/send it from the CRM."""
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    result = service.users().drafts().list(userId="me").execute()
    draft_stubs = result.get("drafts") or []

    matches: list[dict[str, Any]] = []
    for stub in draft_stubs:
        draft = service.users().drafts().get(userId="me", id=stub["id"], format="full").execute()
        message = draft.get("message") or {}
        if message.get("threadId") != thread_id:
            continue
        payload = message.get("payload") or {}
        headers = payload.get("headers") or []
        subject = ""
        for header in headers:
            if str(header.get("name", "")).lower() == "subject":
                subject = str(header.get("value") or "")
                break
        matches.append(
            {
                "draft_id": draft.get("id"),
                "subject": subject,
                "body_text": _extract_message_text(payload),
            }
        )
    return matches


def sync_relevant_threads(db: Session, credentials_info: dict[str, Any], query: str) -> int:
    service = _build_service(credentials_info)
    result = service.users().messages().list(userId="me", q=query).execute()
    messages = result.get("messages") or []
    saved = 0

    for item in messages:
        message = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
        payload = message.get("payload") or {}
        headers = payload.get("headers") or []
        tenant = _find_tenant(db, headers)
        if tenant is None:
            continue

        subject = ""
        for header in headers:
            if str(header.get("name", "")).lower() == "subject":
                subject = str(header.get("value") or "")
                break

        internal_date = _parse_internal_date(message.get("internalDate"))
        exists = (
            db.query(Communication)
            .filter(Communication.tenant_id == tenant.id)
            .filter(Communication.channel == "email")
            .filter(Communication.subject == subject)
            .filter(Communication.created_at == internal_date)
            .first()
        )
        if exists is not None:
            continue

        db.add(
            Communication(
                tenant_id=tenant.id,
                channel="email",
                subject=subject or None,
                message=_extract_message_text(payload) or "",
                created_at=internal_date,
            )
        )
        saved += 1

    if saved:
        db.commit()
    return saved
