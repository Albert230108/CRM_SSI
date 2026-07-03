import base64
import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from jose import jwt
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet

from app.core.dependencies import get_current_user, get_db
from app.core.security import ALGORITHM, SECRET_KEY, generate_secure_token
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.gmail_integration import ConversationRead, GmailAccountRead

router = APIRouter(prefix="/api/integrations/gmail", tags=["gmail"])
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
PROVIDER_GMAIL = "gmail"
FRONTEND_SETTINGS_PATH = "/settings"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment")
    return value


def _oauth_client_config() -> dict[str, Any]:
    return {
        "web": {
            "client_id": _require_env("GOOGLE_OAUTH_CLIENT_ID"),
            "client_secret": _require_env("GOOGLE_OAUTH_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_require_env("GOOGLE_OAUTH_REDIRECT_URI")],
        }
    }


def _oauth_redirect_uri() -> str:
    return _require_env("GOOGLE_OAUTH_REDIRECT_URI")


def _cipher() -> Fernet:
    return Fernet(_require_env("GMAIL_TOKEN_ENCRYPTION_KEY").encode("utf-8"))


def _encrypt_refresh_token(refresh_token: str) -> str:
    return _cipher().encrypt(refresh_token.encode("utf-8")).decode("utf-8")


def _decrypt_refresh_token(encrypted_refresh_token: str | None) -> str | None:
    if not encrypted_refresh_token:
        return None
    return _cipher().decrypt(encrypted_refresh_token.encode("utf-8")).decode("utf-8")


def _build_flow(state: str | None = None) -> Flow:
    return Flow.from_client_config(_oauth_client_config(), scopes=GMAIL_SCOPES, state=state)


def _account_credentials(account: GmailAccount) -> Credentials:
    refresh_token = _decrypt_refresh_token(account.refresh_token_encrypted)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account is missing a refresh token")
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=account.token_uri or "https://oauth2.googleapis.com/token",
        client_id=_require_env("GOOGLE_OAUTH_CLIENT_ID"),
        client_secret=_require_env("GOOGLE_OAUTH_CLIENT_SECRET"),
        scopes=account.scopes_json or GMAIL_SCOPES,
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleAuthRequest())
    return credentials


def _build_service(credentials: Credentials) -> Any:
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _build_service_for_account(account: GmailAccount) -> Any:
    return _build_service(_account_credentials(account))


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


def _gmail_profile(credentials: Credentials) -> dict[str, Any]:
    service = _build_service(credentials)
    return service.users().getProfile(userId="me").execute()


def _mailbox_label(account: GmailAccount) -> str:
    if account.display_name:
        return f"{account.display_name} <{account.email_address}>"
    return account.email_address


def _upsert_account_from_credentials(
    db: Session,
    *,
    account_id: int | None,
    display_name: str | None,
    credentials: Credentials,
) -> GmailAccount:
    profile = _gmail_profile(credentials)
    email_address = str(profile.get("emailAddress") or "").strip().lower()
    if not email_address:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return an email address")

    existing = None
    if account_id is not None:
        existing = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if existing is None:
        existing = db.query(GmailAccount).filter(GmailAccount.email_address == email_address).first()

    refresh_token = credentials.refresh_token
    if not refresh_token and existing is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return a refresh token")

    encrypted_refresh_token = _encrypt_refresh_token(refresh_token) if refresh_token else None
    scopes_json = list(credentials.scopes or GMAIL_SCOPES)

    if existing is None:
        account = GmailAccount(
            email_address=email_address,
            display_name=display_name,
            refresh_token_encrypted=encrypted_refresh_token,
            token_uri=credentials.token_uri or "https://oauth2.googleapis.com/token",
            scopes_json=scopes_json,
            is_active=True,
        )
        db.add(account)
    else:
        account = existing
        account.email_address = email_address
        if display_name is not None:
            account.display_name = display_name
        if encrypted_refresh_token:
            account.refresh_token_encrypted = encrypted_refresh_token
        account.token_uri = credentials.token_uri or "https://oauth2.googleapis.com/token"
        account.scopes_json = scopes_json
        account.is_active = True

    account.google_account_id = str(profile.get("id") or account.google_account_id or email_address)
    db.commit()
    db.refresh(account)
    return account


@router.get("/oauth/start")
def start_oauth(
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    if account_id is not None and db.query(GmailAccount).filter(GmailAccount.id == account_id).first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail account not found")

    state = jwt.encode(
        {
            "sub": str(current_user.id),
            "account_id": account_id,
            "nonce": generate_secure_token(),
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    flow = _build_flow(state=state)
    flow.redirect_uri = _oauth_redirect_uri()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return {"authorization_url": auth_url}


@router.get("/oauth/callback")
def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth callback parameters")

    try:
        state_payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state") from exc

    account_id = state_payload.get("account_id")
    if account_id is not None:
        account_id = int(account_id)

    flow = _build_flow(state=state)
    flow.redirect_uri = _oauth_redirect_uri()
    flow.fetch_token(code=code)
    credentials = flow.credentials

    account = _upsert_account_from_credentials(
        db,
        account_id=account_id,
        display_name=None,
        credentials=credentials,
    )
    target = urlencode({"gmail_oauth": "connected", "account": account.email_address})
    return RedirectResponse(url=f"{FRONTEND_SETTINGS_PATH}?{target}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/accounts", response_model=list[GmailAccountRead])
def list_accounts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[GmailAccount]:
    return db.query(GmailAccount).order_by(GmailAccount.id.desc()).all()


@router.post("/accounts/{account_id}/reconnect")
def reconnect_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, str]:
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail account not found")
    state = jwt.encode(
        {
            "sub": str(current_user.id),
            "account_id": account_id,
            "nonce": generate_secure_token(),
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    flow = _build_flow(state=state)
    flow.redirect_uri = _oauth_redirect_uri()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return {"authorization_url": auth_url}


@router.post("/accounts/{account_id}/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> None:
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail account not found")
    account.is_active = False
    account.refresh_token_encrypted = None
    account.token_uri = None
    account.scopes_json = None
    db.commit()


@router.post("/accounts/sync-all")
def sync_all_accounts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, int]:
    accounts = db.query(GmailAccount).filter(GmailAccount.is_active.is_(True)).order_by(GmailAccount.id.asc()).all()
    synced_accounts = 0
    synced_threads = 0
    for account in accounts:
        result = sync_account(account.id, db=db, current_user=current_user)
        if result.get("synced_threads", 0) >= 0:
            synced_accounts += 1
            synced_threads += int(result.get("synced_threads", 0))
    return {"synced_accounts": synced_accounts, "synced_threads": synced_threads}

@router.post("/accounts/{account_id}/sync")
def sync_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, int | str]:
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail account not found")
    if not account.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account is inactive")

    service = _build_service_for_account(account)
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
    account_lookup = {account.id: account for account in db.query(GmailAccount).all()}
    result: list[Conversation] = []
    for conversation in conversations:
        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.sent_at.asc(), ConversationMessage.id.asc())
            .all()
        )
        mailbox = account_lookup.get(conversation.provider_account_id)
        setattr(conversation, "messages", messages)
        setattr(conversation, "provider_account_email", mailbox.email_address if mailbox else None)
        setattr(conversation, "provider_account_display_name", mailbox.display_name if mailbox else None)
        result.append(conversation)
    return result
