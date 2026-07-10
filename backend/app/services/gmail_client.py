import base64
import os
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.models.communication import Communication
from app.models.tenant import Tenant

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"]


def _build_service(credentials_info: dict[str, Any]) -> Any:
    credentials = Credentials.from_authorized_user_info(credentials_info, scopes=GMAIL_SCOPES)
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
    return db.query(Tenant).filter(Tenant.email == email).first()


def send_gmail_reply(
    credentials: Credentials,
    *,
    thread_id: str,
    to_email: str,
    subject: str,
    body_text: str,
    from_email: str,
    in_reply_to_message_id: str | None = None,
    references: str | None = None,
) -> dict[str, Any]:
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    message = EmailMessage()
    message["To"] = to_email
    message["From"] = from_email
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    message["Subject"] = subject
    if in_reply_to_message_id:
        message["In-Reply-To"] = in_reply_to_message_id
    if references:
        message["References"] = references
    message.set_content(body_text)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw_message, "threadId": thread_id},
    ).execute()
    return result


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
