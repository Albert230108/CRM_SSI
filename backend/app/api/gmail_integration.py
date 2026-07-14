import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from jose import jwt
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet

from app.core.dependencies import get_current_admin_user, get_current_user, get_db
from app.core.security import ALGORITHM, SECRET_KEY, generate_secure_token
from app.database import SessionLocal
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.gmail_integration import ConversationRead, GmailAccountRead
from app.services.background_jobs import get_job, start_job

router = APIRouter(prefix="/api/integrations/gmail", tags=["gmail"])
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"]
PROVIDER_GMAIL = "gmail"
FRONTEND_SETTINGS_PATH = "/settings"
logger = logging.getLogger(__name__)
_oauth_code_verifiers: dict[str, tuple[str, datetime]] = {}


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


def _oauth_state_key(state: str | None) -> str | None:
    if not state:
        return None
    try:
        payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return state
    nonce = payload.get("nonce")
    return str(nonce) if nonce else state


def _store_oauth_code_verifier(state: str | None, code_verifier: str) -> None:
    state_key = _oauth_state_key(state)
    if not state_key:
        return
    _oauth_code_verifiers[state_key] = (code_verifier, datetime.now(timezone.utc) + timedelta(minutes=15))


def _pop_oauth_code_verifier(state: str | None) -> str | None:
    state_key = _oauth_state_key(state)
    if not state_key:
        return None
    stored = _oauth_code_verifiers.pop(state_key, None)
    if not stored:
        return None
    code_verifier, expires_at = stored
    if expires_at < datetime.now(timezone.utc):
        return None
    return code_verifier


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
    if data and str(payload.get("mimeType") or "").lower() != "text/html":
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/plain" and (part.get("body") or {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"].encode("utf-8")).decode("utf-8", errors="ignore")
        nested = _extract_text(part)
        if nested:
            return nested
    return ""


def _extract_html(payload: dict[str, Any]) -> str:
    body = payload.get("body") or {}
    data = body.get("data")
    if data and str(payload.get("mimeType") or "").lower() == "text/html":
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/html" and (part.get("body") or {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"].encode("utf-8")).decode("utf-8", errors="ignore")
        nested = _extract_html(part)
        if nested:
            return nested
    return ""


def _extract_attachments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for part in payload.get("parts") or []:
        filename = part.get("filename") or ""
        attachment_id = (part.get("body") or {}).get("attachmentId")
        if filename and attachment_id:
            attachments.append(
                {
                    "attachment_id": attachment_id,
                    "filename": filename,
                    "mime_type": part.get("mimeType"),
                    "size": (part.get("body") or {}).get("size"),
                }
            )
        attachments.extend(_extract_attachments(part))
    return attachments


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



def _thread_email_candidates(messages: list[dict[str, Any]], account_email: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    account_email = account_email.lower()
    for message in messages:
        payload = message.get("payload") or {}
        headers = _headers_map(payload.get("headers") or [])
        for field in ("from", "to", "cc", "bcc"):
            raw_value = headers.get(field)
            if not raw_value:
                continue
            for candidate in raw_value.split(','):
                address = _email_address(candidate)
                if address and address != account_email and address not in seen:
                    seen.add(address)
                    candidates.append(address)
    return candidates


def _find_existing_conversation_for_thread(db: Session, thread: dict[str, Any]) -> Conversation | None:
    for message in thread.get("messages") or []:
        provider_message_id = str(message.get("id") or "")
        if not provider_message_id:
            continue
        existing_message = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.provider == PROVIDER_GMAIL)
            .filter(ConversationMessage.provider_message_id == provider_message_id)
            .first()
        )
        if existing_message is None:
            continue
        conversation = db.query(Conversation).filter(Conversation.id == existing_message.conversation_id).first()
        if conversation is not None and conversation.provider == PROVIDER_GMAIL:
            return conversation
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
        conversation = _find_existing_conversation_for_thread(db, thread)
    if conversation is None:
        conversation = Conversation(
            provider=PROVIDER_GMAIL,
            provider_account_id=account.id,
            provider_thread_id=thread_id,
        )
        db.add(conversation)
        db.flush()
    else:
        if conversation.provider != PROVIDER_GMAIL:
            conversation.provider = PROVIDER_GMAIL
        if conversation.provider_account_id is None:
            conversation.provider_account_id = account.id
        if not conversation.provider_thread_id:
            conversation.provider_thread_id = thread_id

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
        body_html = _extract_html(payload)
        attachments = _extract_attachments(payload)
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
                raw_payload={"gmail": message, "body_text": body_text, "body_html": body_html, "attachments": attachments},
            )
        )

    if tenant is None and conversation.tenant_id is not None:
        tenant = db.query(Tenant).filter(Tenant.id == conversation.tenant_id).first()
    tenant_email_candidates = _thread_email_candidates(messages, account_email)
    if tenant is not None and not tenant.email and len(tenant_email_candidates) == 1:
        tenant.email = tenant_email_candidates[0]

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
    code_verifier = generate_secure_token() + generate_secure_token()
    flow.code_verifier = code_verifier
    _store_oauth_code_verifier(state, code_verifier)
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

    stored_code_verifier = _pop_oauth_code_verifier(state)
    flow = _build_flow(state=state)
    flow.redirect_uri = _oauth_redirect_uri()
    flow.code_verifier = stored_code_verifier
    logger.debug(
        "Gmail OAuth callback: pkce_enabled=%s stored_verifier_found=%s code_verifier_length=%s redirect_uri=%s",
        True,
        stored_code_verifier is not None,
        len(stored_code_verifier) if stored_code_verifier else 0,
        flow.redirect_uri,
    )
    if not stored_code_verifier:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth PKCE code verifier")
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        logger.exception("Gmail OAuth token exchange failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gmail token exchange failed") from exc
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


def _sync_all_accounts_blocking(user_id: int) -> dict[str, int]:
    """Runs the full account sync against its own DB session, off the event loop.

    Gmail thread listing/fetching can take a long time across many accounts, so this
    is meant to be invoked via start_job()/asyncio.to_thread rather than awaited inline.
    """
    db = SessionLocal()
    try:
        current_user = db.query(User).filter(User.id == user_id).first()
        accounts = db.query(GmailAccount).filter(GmailAccount.is_active.is_(True)).order_by(GmailAccount.id.asc()).all()
        synced_accounts = 0
        synced_threads = 0
        for account in accounts:
            result = sync_account(account.id, db=db, current_user=current_user)
            if result.get("synced_threads", 0) >= 0:
                synced_accounts += 1
                synced_threads += int(result.get("synced_threads", 0))
        return {"synced_accounts": synced_accounts, "synced_threads": synced_threads}
    finally:
        db.close()


@router.post("/accounts/sync-all")
def sync_all_accounts(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    job_id = start_job("gmail_sync_all", asyncio.to_thread(_sync_all_accounts_blocking, current_user.id))
    return {"queued": True, "job_id": job_id}


@router.get("/accounts/sync-status/{job_id}")
def sync_all_accounts_status(job_id: str, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync job not found")
    return job

def _sync_gmail_account(db: Session, account: GmailAccount) -> int:
    """Sync a single active Gmail account's threads. Returns count of saved conversations.

    Shared by the manual sync route and the background poller in app.main, so both paths
    stay in sync as Gmail sync logic evolves.
    """
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
    return saved


@router.post("/accounts/{account_id}/sync")
def sync_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, int | str]:
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail account not found")
    if not account.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gmail account is inactive")

    saved = _sync_gmail_account(db, account)
    return {"synced_threads": saved, "account_id": account.id}


def _backfill_message_bodies(db: Session) -> dict[str, int]:
    """Re-extract body/body_html for already-synced messages from their stored raw Gmail payload.

    Fixes rows persisted before the MIME-recursion fix in `_extract_text`/`_extract_html`
    (e.g. a nested multipart/alternative part, common in outbound mail with a signature,
    used to yield an empty body while the subject still came through). No Gmail API calls
    are made; this only re-derives fields from the `raw_payload.gmail` JSON already stored.
    """
    scanned = 0
    updated = 0
    messages = db.query(ConversationMessage).filter(ConversationMessage.provider == PROVIDER_GMAIL).all()
    for message in messages:
        raw_payload = message.raw_payload
        if not isinstance(raw_payload, dict):
            continue
        gmail_message = raw_payload.get("gmail")
        if not isinstance(gmail_message, dict) or "payload" not in gmail_message:
            # Manually-sent replies only store the Gmail send-API response (id/threadId),
            # not the full message resource, so there is nothing to re-extract from.
            continue
        payload = gmail_message.get("payload") or {}
        scanned += 1

        body_text = _extract_text(payload)
        body_html = _extract_html(payload)
        attachments = _extract_attachments(payload)
        changed = False

        if body_text and body_text != message.body:
            message.body = body_text
            changed = True

        if (
            body_text != raw_payload.get("body_text")
            or body_html != raw_payload.get("body_html")
            or attachments != raw_payload.get("attachments")
        ):
            message.raw_payload = {**raw_payload, "body_text": body_text, "body_html": body_html, "attachments": attachments}
            changed = True

        if changed:
            updated += 1

    if updated:
        db.commit()
    return {"scanned": scanned, "updated": updated}


@router.post("/accounts/backfill-bodies")
def backfill_message_bodies(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> dict[str, int]:
    return _backfill_message_bodies(db)


@router.get("/messages/{conversation_message_id}/attachments/{attachment_id}")
def download_message_attachment(
    conversation_message_id: int,
    attachment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    message = db.query(ConversationMessage).filter(ConversationMessage.id == conversation_message_id).first()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    raw_payload = message.raw_payload if isinstance(message.raw_payload, dict) else {}
    attachments = raw_payload.get("attachments") or []
    attachment_meta = next((item for item in attachments if item.get("attachment_id") == attachment_id), None)
    if attachment_meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found on this message")

    conversation = db.query(Conversation).filter(Conversation.id == message.conversation_id).first()
    if conversation is None or conversation.provider_account_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail account not found for message")
    account = db.query(GmailAccount).filter(GmailAccount.id == conversation.provider_account_id).first()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail account not found for message")

    service = _build_service_for_account(account)
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
    return Response(
        content=data,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

