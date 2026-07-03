import base64
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.gmail_integration import ConversationRead, GmailAccountCreate, GmailAccountRead

router = APIRouter(prefix="/api/integrations/gmail", tags=["gmail"])
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
PROVIDER_GMAIL = "gmail"


def _build_service(credentials_info: dict[str, Any]) -> Any:
    credentials = Credentials.from_authorized_user_info(credentials_info, scopes=GMAIL_SCOPES)
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _parse_internal_date(value: str | int | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def _extract_text(payload: dict[str, Any]) -> str:
    body = payload.get("body") or {}
    data = body.get("data")
    if data:
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/plain" and (part.get("body") or {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"].encode("utf-8")).decode("utf-8", errors="ignore")
    return ""


def _headers_map(headers: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in headers:
        name = str(header.get("name") or "").lower()
        value = str(header.get("value") or "")
        if name:
            result[name] = value
    return result


def _email_address(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    _, email = parseaddr(raw_value)
    return email.strip().lower() if email else raw_value.strip().lower()


def _find_tenant_for_message(db: Session, headers: dict[str, str], account_email: str) -> Tenant | None:
    for field in ("from", "to", "cc", "bcc"):
        raw_value = headers.get(field)
        if not raw_value:
            continue
        for candidate in raw_value.split(","):
            address = _email_address(candidate)
            if address and address != account_email.lower():
                tenant = db.query(Tenant).filter(Tenant.email == address).first()
                if tenant is not None:
                    return tenant
    return None


def _upsert_thread(db: Session, account: GmailAccount, thread: dict[str, Any]) -> Conversation | None:
    messages = thread.get("messages") or []
    if not messages:
        return None

    account_email = account.email_address.lower()
    thread_id = str(thread.get("id") or "")
    conversation = (
        db.query(Conversation)
        .filter(Conversation.provider == PROVIDER_GMAIL)
        .filter(Conversation.provider_account_id == account.id)
        .filter(Conversation.provider_thread_id == thread_id)
        .first()
    )
    if conversation is None:
        conversation = Conversation(
            provider=PROVIDER_GMAIL,
            provider_account_id=account.id,
            provider_thread_id=thread_id,
        )
        db.add(conversation)
        db.flush()

    subject = conversation.subject
    latest_preview = conversation.preview_text
    last_message_at = conversation.last_message_at
    tenant = None

    for message in messages:
        payload = message.get("payload") or {}
        headers = _headers_map(payload.get("headers") or [])
        sender_email = _email_address(headers.get("from"))
        tenant = tenant or _find_tenant_for_message(db, headers, account_email)
        sent_at = _parse_internal_date(message.get("internalDate"))
        if last_message_at is None or sent_at > last_message_at:
            last_message_at = sent_at
            latest_preview = _extract_text(payload)[:500] or latest_preview
        if not subject:
            subject = headers.get("subject")

        provider_message_id = str(message.get("id") or "")
        exists = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.provider == PROVIDER_GMAIL)
            .filter(ConversationMessage.provider_message_id == provider_message_id)
            .first()
        )
        if exists is not None:
            continue

        body_text = _extract_text(payload)
        recipient_email = _email_address(headers.get("to"))
        direction = "outbound" if sender_email and sender_email == account_email else "inbound"

        db.add(
            ConversationMessage(
                conversation_id=conversation.id,
                provider=PROVIDER_GMAIL,
                provider_message_id=provider_message_id,
                direction=direction,
                sender_email=sender_email,
                recipient_email=recipient_email,
                subject=headers.get("subject"),
                body=body_text,
                sent_at=sent_at,
                raw_payload={"gmail": message},
            )
        )

    conversation.subject = subject
    conversation.tenant_id = tenant.id if tenant else conversation.tenant_id
    conversation.last_message_at = last_message_at
    conversation.preview_text = latest_preview
    return conversation


@router.get("/accounts", response_model=list[GmailAccountRead])
def list_accounts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[GmailAccount]:
    return db.query(GmailAccount).order_by(GmailAccount.id.desc()).all()


@router.post("/accounts", response_model=GmailAccountRead, status_code=status.HTTP_201_CREATED)
def create_account(payload: GmailAccountCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> GmailAccount:
    normalized_email = payload.email_address.strip().lower()
    existing = db.query(GmailAccount).filter(GmailAccount.email_address == normalized_email).first()
    if existing is not None:
        existing.display_name = payload.display_name
        existing.credentials_json = payload.credentials_json
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing

    account = GmailAccount(
        email_address=normalized_email,
        display_name=payload.display_name,
        credentials_json=payload.credentials_json,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> None:
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail account not found")
    db.delete(account)
    db.commit()


@router.post("/accounts/{account_id}/sync")
def sync_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, int | str]:
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail account not found")
    if not account.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account is inactive")

    service = _build_service(account.credentials_json)
    tenant_emails = {
        tenant.email.strip().lower()
        for tenant in db.query(Tenant).filter(Tenant.email.isnot(None)).all()
        if tenant.email
    }
    query_parts = [f'"{email}"' for email in sorted(tenant_emails)]
    query = " OR ".join(query_parts) if query_parts else None
    request = service.users().threads().list(userId="me", maxResults=100, q=query) if query else None
    threads = request.execute().get("threads") or [] if request is not None else []
    saved = 0
    for thread_ref in threads:
        thread = service.users().threads().get(userId="me", id=thread_ref["id"], format="full").execute()
        conversation = _upsert_thread(db, account, thread)
        if conversation is not None and conversation.tenant_id is not None:
            saved += 1

    account.last_synced_at = datetime.now(timezone.utc)
    db.commit()
    return {"synced_threads": saved, "account_id": account.id}


@router.get("/tenants/{tenant_id}/conversations", response_model=list[ConversationRead])
def get_tenant_conversations(tenant_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[Conversation]:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    conversations = (
        db.query(Conversation)
        .filter(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.id.desc())
        .all()
    )
    result: list[Conversation] = []
    for conversation in conversations:
        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.sent_at.asc(), ConversationMessage.id.asc())
            .all()
        )
        setattr(conversation, "messages", messages)
        result.append(conversation)
    return result
