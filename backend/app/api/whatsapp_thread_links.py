import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User
from app.schemas.whatsapp_thread_link import (
    ThreadWhatsAppLinkCreate,
    ThreadWhatsAppLinkRead,
    ThreadWhatsAppLinkResyncRead,
    WhatsAppAccountRead,
    WhatsAppChatRead,
    WhatsAppChatResyncResult,
)
from app.services.whatsapp_chat_directory import fetch_whatsapp_chats, list_whatsapp_accounts, resync_whatsapp_chat
from app.services.whatsapp_client import WhatsAppBridgeError

router = APIRouter(tags=["whatsapp-thread-links"])
logger = logging.getLogger(__name__)

MANUAL_LINK_SOURCE = "manual"


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _get_tenant_or_404(db: Session, tenant_id: int) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    return tenant


def _to_link_read(endpoint: TenantChannelEndpoint) -> ThreadWhatsAppLinkRead:
    return ThreadWhatsAppLinkRead(
        id=endpoint.id,
        thread_id=endpoint.tenant_id,
        provider=endpoint.provider,
        external_account_id=endpoint.external_account_id or "",
        chat_id=endpoint.external_chat_namespace or "",
        chat_display_name=endpoint.chat_display_name,
        is_active=endpoint.is_active,
        linked_by_user_id=endpoint.linked_by_user_id,
        unlinked_at=endpoint.unlinked_at,
        unlinked_by_user_id=endpoint.unlinked_by_user_id,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


async def _run_resync(external_account_id: str, chat_id: str) -> None:
    try:
        result = await resync_whatsapp_chat(external_account_id, chat_id)
        logger.info("whatsapp_thread_link_resync_completed external_account_id=%s chat_id=%s result=%s", external_account_id, chat_id, result)
    except WhatsAppBridgeError as exc:
        logger.warning("whatsapp_thread_link_resync_failed external_account_id=%s chat_id=%s error=%s", external_account_id, chat_id, exc)


def _active_whatsapp_links_query(db: Session):
    return db.query(TenantChannelEndpoint).filter(
        TenantChannelEndpoint.channel_type == "whatsapp",
        TenantChannelEndpoint.is_active.is_(True),
    )


@router.get("/whatsapp/accounts", response_model=list[WhatsAppAccountRead])
def get_whatsapp_accounts(current_user: User = Depends(get_current_user)) -> list[WhatsAppAccountRead]:
    return [WhatsAppAccountRead(**account) for account in list_whatsapp_accounts()]


@router.get("/whatsapp/accounts/{external_account_id}/chats", response_model=list[WhatsAppChatRead])
async def get_whatsapp_account_chats(
    external_account_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: str = "whatsapp-service",
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[WhatsAppChatRead]:
    external_account_id = external_account_id.strip()
    normalized_search = _normalize_text(search)
    try:
        raw_chats = await fetch_whatsapp_chats(external_account_id, search=normalized_search, limit=limit, offset=offset)
    except WhatsAppBridgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.args[0] if exc.args else "Failed to fetch WhatsApp chats") from exc

    existing_links = {
        (link.provider, link.external_account_id, link.external_chat_namespace): link.tenant_id
        for link in _active_whatsapp_links_query(db).filter(TenantChannelEndpoint.external_account_id == external_account_id).all()
    }

    chats: list[WhatsAppChatRead] = []
    for raw_chat in raw_chats:
        if not isinstance(raw_chat, dict):
            continue
        chat_id = str(raw_chat.get("chat_id") or "").strip()
        if not chat_id:
            continue
        chat_provider = str(raw_chat.get("provider") or provider).strip() or provider
        if normalized_search and normalized_search.lower() not in chat_id.lower() and normalized_search.lower() not in str(raw_chat.get("chat_name") or "").lower():
            continue
        linked_thread_id = existing_links.get((chat_provider, external_account_id, chat_id))
        chats.append(
            WhatsAppChatRead(
                chat_id=chat_id,
                chat_name=_normalize_text(raw_chat.get("chat_name")),
                provider=chat_provider,
                external_account_id=external_account_id,
                last_message_timestamp=raw_chat.get("last_message_timestamp"),
                last_message_preview=_normalize_text(raw_chat.get("last_message_preview")),
                already_linked=linked_thread_id is not None,
                linked_thread_id=linked_thread_id,
            )
        )

    logger.info(
        "whatsapp_chat_list_fetched external_account_id=%s search=%s result_count=%s actor_user_id=%s",
        external_account_id,
        normalized_search,
        len(chats),
        current_user.id,
    )
    return chats


@router.get("/threads/{thread_id}/whatsapp-links", response_model=list[ThreadWhatsAppLinkRead])
def get_thread_whatsapp_links(
    thread_id: int,
    include_history: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ThreadWhatsAppLinkRead]:
    _get_tenant_or_404(db, thread_id)
    query = db.query(TenantChannelEndpoint).filter(
        TenantChannelEndpoint.tenant_id == thread_id,
        TenantChannelEndpoint.channel_type == "whatsapp",
    )
    if not include_history:
        query = query.filter(TenantChannelEndpoint.is_active.is_(True))
    links = query.order_by(TenantChannelEndpoint.created_at.desc(), TenantChannelEndpoint.id.desc()).all()
    return [_to_link_read(link) for link in links]


@router.post("/threads/{thread_id}/whatsapp-links", response_model=ThreadWhatsAppLinkRead)
def create_thread_whatsapp_link(
    thread_id: int,
    payload: ThreadWhatsAppLinkCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadWhatsAppLinkRead:
    _get_tenant_or_404(db, thread_id)

    provider = payload.provider
    external_account_id = payload.external_account_id
    chat_id = payload.chat_id
    chat_display_name = _normalize_text(payload.chat_display_name)

    conflicting_link = (
        _active_whatsapp_links_query(db)
        .filter(
            TenantChannelEndpoint.provider == provider,
            TenantChannelEndpoint.external_account_id == external_account_id,
            TenantChannelEndpoint.external_chat_namespace == chat_id,
        )
        .first()
    )
    if conflicting_link is not None and conflicting_link.tenant_id != thread_id:
        logger.warning(
            "whatsapp_thread_link_conflict thread_id=%s provider=%s external_account_id=%s chat_id=%s "
            "conflicting_thread_id=%s actor_user_id=%s",
            thread_id,
            provider,
            external_account_id,
            chat_id,
            conflicting_link.tenant_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This WhatsApp chat is already linked to another thread (thread_id={conflicting_link.tenant_id})",
        )

    existing_thread_link = (
        _active_whatsapp_links_query(db)
        .filter(
            TenantChannelEndpoint.tenant_id == thread_id,
            TenantChannelEndpoint.provider == provider,
            TenantChannelEndpoint.external_account_id == external_account_id,
        )
        .first()
    )
    if existing_thread_link is not None:
        if existing_thread_link.external_chat_namespace == chat_id:
            # Re-linking the exact same chat: nothing to replace, just refresh the display name.
            existing_thread_link.chat_display_name = chat_display_name or existing_thread_link.chat_display_name
            db.commit()
            db.refresh(existing_thread_link)
            return _to_link_read(existing_thread_link)

        if not payload.replace_existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Thread already has a linked WhatsApp chat for this account. Set replace_existing=true to replace it.",
            )

        now = datetime.now(timezone.utc)
        existing_thread_link.is_active = False
        existing_thread_link.unlinked_at = now
        existing_thread_link.unlinked_by_user_id = current_user.id

    new_link = TenantChannelEndpoint(
        tenant_id=thread_id,
        channel_type="whatsapp",
        provider=provider,
        external_account_id=external_account_id,
        external_chat_namespace=chat_id,
        chat_display_name=chat_display_name,
        source=MANUAL_LINK_SOURCE,
        is_active=True,
        linked_by_user_id=current_user.id,
    )
    db.add(new_link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This WhatsApp chat is already linked elsewhere") from exc
    db.refresh(new_link)

    # Force a full-history resync for the newly linked chat instead of waiting for the next
    # scheduled sweep, and so this pulls the chat's *entire* history rather than only whatever
    # was captured by a previous capped sync.
    background_tasks.add_task(_run_resync, external_account_id, chat_id)

    if existing_thread_link is not None:
        logger.info(
            "whatsapp_thread_link_replaced thread_id=%s provider=%s external_account_id=%s old_chat_id=%s new_chat_id=%s "
            "actor_user_id=%s",
            thread_id,
            provider,
            external_account_id,
            existing_thread_link.external_chat_namespace,
            chat_id,
            current_user.id,
        )
    else:
        logger.info(
            "whatsapp_thread_link_created thread_id=%s provider=%s external_account_id=%s chat_id=%s actor_user_id=%s",
            thread_id,
            provider,
            external_account_id,
            chat_id,
            current_user.id,
        )

    return _to_link_read(new_link)


@router.post("/threads/{thread_id}/whatsapp-links/{link_id}/resync", response_model=ThreadWhatsAppLinkResyncRead)
async def resync_thread_whatsapp_link(
    thread_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadWhatsAppLinkResyncRead:
    """Force a full-history resync of an already-linked chat, e.g. if it was linked before the
    full-history fix shipped and only its most recent messages were imported.

    Runs synchronously (awaits the whatsapp-service backfill call) so the response itself is the
    completion signal the UI needs — a fire-and-forget background task left the "Resync" button
    stuck showing "queued" forever with no way to know when it actually finished.
    """
    _get_tenant_or_404(db, thread_id)
    link = (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.id == link_id,
            TenantChannelEndpoint.tenant_id == thread_id,
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.is_active.is_(True),
        )
        .first()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active WhatsApp link not found")

    logger.info(
        "whatsapp_thread_link_resync_requested thread_id=%s link_id=%s provider=%s external_account_id=%s chat_id=%s actor_user_id=%s",
        thread_id,
        link_id,
        link.provider,
        link.external_account_id,
        link.external_chat_namespace,
        current_user.id,
    )

    try:
        raw_result = await resync_whatsapp_chat(link.external_account_id, link.external_chat_namespace)
        resync_result = WhatsAppChatResyncResult(
            ok=bool(raw_result.get("ok", True)),
            fetched=int(raw_result.get("fetched") or 0),
            imported=int(raw_result.get("imported") or 0),
            deduped=int(raw_result.get("deduped") or 0),
            skipped_no_content=int(raw_result.get("skippedNoContent") or 0),
            failed=int(raw_result.get("failed") or 0),
        )
        logger.info(
            "whatsapp_thread_link_resync_completed thread_id=%s link_id=%s result=%s",
            thread_id,
            link_id,
            raw_result,
        )
    except WhatsAppBridgeError as exc:
        resync_result = WhatsAppChatResyncResult(ok=False, error=exc.args[0] if exc.args else "Resync failed")
        logger.warning(
            "whatsapp_thread_link_resync_failed thread_id=%s link_id=%s error=%s",
            thread_id,
            link_id,
            exc,
        )

    return ThreadWhatsAppLinkResyncRead(link=_to_link_read(link), resync=resync_result)


@router.delete("/threads/{thread_id}/whatsapp-links/{link_id}", response_model=ThreadWhatsAppLinkRead)
def delete_thread_whatsapp_link(
    thread_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadWhatsAppLinkRead:
    _get_tenant_or_404(db, thread_id)
    link = (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.id == link_id,
            TenantChannelEndpoint.tenant_id == thread_id,
            TenantChannelEndpoint.channel_type == "whatsapp",
        )
        .first()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp link not found")
    if not link.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="WhatsApp link is already unlinked")

    link.is_active = False
    link.unlinked_at = datetime.now(timezone.utc)
    link.unlinked_by_user_id = current_user.id
    db.commit()
    db.refresh(link)

    logger.info(
        "whatsapp_thread_link_removed thread_id=%s link_id=%s provider=%s external_account_id=%s chat_id=%s actor_user_id=%s",
        thread_id,
        link_id,
        link.provider,
        link.external_account_id,
        link.external_chat_namespace,
        current_user.id,
    )
    return _to_link_read(link)
