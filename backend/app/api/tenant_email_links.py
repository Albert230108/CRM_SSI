import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.gmail_integration import sync_email_across_gmail_accounts
from app.core.dependencies import get_current_user, get_db
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant_email_address import TenantEmailAddress
from app.models.user import User
from app.schemas.tenant_email_link import (
    TenantAutoAddThreadsRead,
    TenantAutoAddThreadsUpdate,
    TenantConversationVisibilityRead,
    TenantConversationVisibilityUpdate,
    TenantEmailLinkCreate,
    TenantEmailLinkCreateRead,
    TenantEmailLinkDeleteRead,
    TenantEmailLinkRead,
)
from app.services.background_jobs import start_job
from app.services.beds24_client import BEDS24_EMAIL_INFO_CODE, add_booking_info_item, delete_booking_info_item, get_booking_info_items
from app.services.tenant_conversation_links import remove_conversations_for_matched_email

router = APIRouter(tags=["tenant-email-links"])
logger = logging.getLogger(__name__)

MANUAL_LINK_SOURCE = "manual"


def _get_tenant_or_404(db: Session, tenant_id: int) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _active_email_links_query(db: Session):
    return db.query(TenantEmailAddress).filter(TenantEmailAddress.is_active.is_(True))


@router.get("/tenants/{tenant_id}/email-links", response_model=list[TenantEmailLinkRead])
def get_tenant_email_links(
    tenant_id: int,
    include_history: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TenantEmailLinkRead]:
    _get_tenant_or_404(db, tenant_id)
    query = db.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant_id)
    if not include_history:
        query = query.filter(TenantEmailAddress.is_active.is_(True))
    links = query.order_by(TenantEmailAddress.created_at.desc(), TenantEmailAddress.id.desc()).all()
    return list(links)


@router.post("/tenants/{tenant_id}/email-links", response_model=TenantEmailLinkCreateRead)
async def create_tenant_email_link(
    tenant_id: int,
    payload: TenantEmailLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantEmailLinkCreateRead:
    tenant = _get_tenant_or_404(db, tenant_id)
    email = payload.email

    same_tenant_existing_link = (
        _active_email_links_query(db)
        .filter(TenantEmailAddress.tenant_id == tenant_id, TenantEmailAddress.email == email)
        .first()
    )
    if same_tenant_existing_link is not None:
        return TenantEmailLinkCreateRead(link=TenantEmailLinkRead.model_validate(same_tenant_existing_link), gmail_sync_job_id=None)

    conflicting_link = (
        _active_email_links_query(db)
        .filter(TenantEmailAddress.email == email, TenantEmailAddress.tenant_id != tenant_id)
        .first()
    )
    if conflicting_link is not None and not payload.confirm_conflict:
        conflicting_tenant = db.query(Tenant).filter(Tenant.id == conflicting_link.tenant_id).first()
        logger.warning(
            "tenant_email_link_conflict tenant_id=%s email=%s conflicting_tenant_id=%s actor_user_id=%s",
            tenant_id,
            email,
            conflicting_link.tenant_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This email is already linked to another tenant",
                "conflicting_tenant_id": conflicting_link.tenant_id,
                "conflicting_tenant_name": conflicting_tenant.name if conflicting_tenant else None,
            },
        )

    new_link = TenantEmailAddress(
        tenant_id=tenant_id,
        email=email,
        source=MANUAL_LINK_SOURCE,
        is_active=True,
        beds24_sync_status="pending",
        linked_by_user_id=current_user.id,
    )
    db.add(new_link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This email could not be linked") from exc
    db.refresh(new_link)

    await _push_link_to_beds24(tenant, new_link)
    db.commit()
    db.refresh(new_link)

    # Search existing Gmail history for this address across every connected account, so past
    # messages involving it surface in this tenant's thread instead of only future ones -- the
    # regular account-wide sync query is built from Tenant.email only, so a newly linked
    # secondary address wouldn't otherwise get searched for. Tracked as a job (rather than a
    # fire-and-forget background task) so the frontend can poll it and show progress/outcome.
    gmail_sync_job_id = start_job("gmail_sync_email", asyncio.to_thread(sync_email_across_gmail_accounts, email))

    logger.info(
        "tenant_email_link_created tenant_id=%s email=%s beds24_sync_status=%s gmail_sync_job_id=%s actor_user_id=%s",
        tenant_id,
        email,
        new_link.beds24_sync_status,
        gmail_sync_job_id,
        current_user.id,
    )
    return TenantEmailLinkCreateRead(link=TenantEmailLinkRead.model_validate(new_link), gmail_sync_job_id=gmail_sync_job_id)


@router.delete("/tenants/{tenant_id}/email-links/{link_id}", response_model=TenantEmailLinkDeleteRead)
async def delete_tenant_email_link(
    tenant_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantEmailLinkDeleteRead:
    tenant = _get_tenant_or_404(db, tenant_id)
    link = (
        db.query(TenantEmailAddress)
        .filter(
            TenantEmailAddress.id == link_id,
            TenantEmailAddress.tenant_id == tenant_id,
            TenantEmailAddress.is_active.is_(True),
        )
        .first()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active email link not found")

    now = datetime.now(timezone.utc)
    link.is_active = False
    link.unlinked_at = now
    link.unlinked_by_user_id = current_user.id

    info_item_id = link.beds24_info_item_id
    if not info_item_id:
        # The id wasn't captured when the link was created (e.g. an older link created before
        # this lookup existed) -- find the matching info item on the booking so it still gets
        # cleaned up in Beds24 instead of being silently orphaned there.
        try:
            for item in await get_booking_info_items(tenant.booking_id):
                if item.get("code") == BEDS24_EMAIL_INFO_CODE and item.get("text") == link.email and item.get("id") is not None:
                    info_item_id = str(item["id"])
                    break
        except HTTPException as exc:
            logger.warning(
                "tenant_email_link_beds24_lookup_failed tenant_id=%s link_id=%s error=%s",
                tenant_id,
                link_id,
                exc.detail,
            )

    if info_item_id:
        try:
            await delete_booking_info_item(tenant.booking_id, info_item_id)
            link.beds24_sync_status = "synced"
        except HTTPException as exc:
            logger.warning(
                "tenant_email_link_beds24_unsync_failed tenant_id=%s link_id=%s error=%s",
                tenant_id,
                link_id,
                exc.detail,
            )
            link.beds24_sync_status = "failed"

    deleted_conversations, shared_conversations_unlinked = remove_conversations_for_matched_email(db, tenant_id, link.email)

    db.commit()
    db.refresh(link)

    logger.info(
        "tenant_email_link_unlinked tenant_id=%s link_id=%s deleted_conversations=%s shared_conversations_unlinked=%s actor_user_id=%s",
        tenant_id,
        link_id,
        deleted_conversations,
        shared_conversations_unlinked,
        current_user.id,
    )
    return TenantEmailLinkDeleteRead(
        link=TenantEmailLinkRead.model_validate(link),
        deleted_conversations=deleted_conversations,
        shared_conversations_unlinked=shared_conversations_unlinked,
    )


async def _push_link_to_beds24(tenant: Tenant, link: TenantEmailAddress) -> None:
    """Write `link` to its booking as a CRM_EMAIL info item and record the outcome.

    A failure never undoes the CRM-side link - it is recorded via beds24_sync_status so it can
    be retried, since the link is still what drives Gmail matching even when Beds24 is
    unreachable. Does not commit; the caller owns the transaction.
    """
    try:
        info_item = await add_booking_info_item(tenant.booking_id, BEDS24_EMAIL_INFO_CODE, link.email)
        link.beds24_info_item_id = str(info_item["id"]) if info_item and info_item.get("id") is not None else None
        link.beds24_sync_status = "synced" if info_item else "failed"
    except HTTPException as exc:
        logger.warning(
            "tenant_email_link_beds24_sync_failed tenant_id=%s email=%s error=%s",
            link.tenant_id,
            link.email,
            exc.detail,
        )
        link.beds24_sync_status = "failed"


@router.post("/tenants/{tenant_id}/email-links/{link_id}/sync-beds24", response_model=TenantEmailLinkRead)
async def sync_email_link_to_beds24(
    tenant_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantEmailLinkRead:
    """Push one CRM_EMAIL link to its Beds24 booking on demand.

    Backfilled links (and any link whose original push failed) exist in the CRM without a
    matching info item on the booking. This is the explicit, per-link operator action that
    reconciles them - deliberately not done in bulk, since each call writes to a live booking.
    """
    tenant = _get_tenant_or_404(db, tenant_id)
    link = (
        db.query(TenantEmailAddress)
        .filter(TenantEmailAddress.id == link_id, TenantEmailAddress.tenant_id == tenant_id)
        .first()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email link not found")
    if not link.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This email link is not active")
    if not tenant.booking_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant has no Beds24 booking to sync to")

    await _push_link_to_beds24(tenant, link)
    db.commit()
    db.refresh(link)
    logger.info(
        "tenant_email_link_beds24_manual_sync tenant_id=%s email=%s status=%s actor_user_id=%s",
        tenant_id,
        link.email,
        link.beds24_sync_status,
        current_user.id,
    )
    return link


@router.get("/tenants/{tenant_id}/shared-threads", response_model=list[TenantConversationVisibilityRead])
def get_tenant_shared_threads(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TenantConversationVisibilityRead]:
    """List every Gmail conversation linked to this tenant, with a last-message preview and
    whether it's also linked to another tenant.

    The "Manage emails" UI offers a visibility toggle on every thread, not just genuinely
    shared ones: an operator who wants a thread off a tenant's timeline needs that control
    to exist regardless of why the thread is noisy. `shared_with_other_tenants` is still
    reported so the UI can flag the threads where hiding has cross-tenant consequences.
    """
    _get_tenant_or_404(db, tenant_id)
    links = (
        db.query(TenantConversationLink)
        .filter(TenantConversationLink.tenant_id == tenant_id, TenantConversationLink.unlinked_at.is_(None))
        .all()
    )
    if not links:
        return []

    conversation_ids = [link.conversation_id for link in links]
    conversations_by_id = {
        conversation.id: conversation
        for conversation in db.query(Conversation).filter(Conversation.id.in_(conversation_ids)).all()
    }
    shared_conversation_ids = {
        row[0]
        for row in db.query(TenantConversationLink.conversation_id)
        .filter(
            TenantConversationLink.conversation_id.in_(conversation_ids),
            TenantConversationLink.tenant_id != tenant_id,
            TenantConversationLink.unlinked_at.is_(None),
        )
        .distinct()
        .all()
    }

    # Newest message per conversation in one pass, so the list renders a real "last
    # sent/received" preview without an N+1 query per thread.
    latest_by_conversation: dict[int, ConversationMessage] = {}
    for message in (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id.in_(conversation_ids))
        .order_by(ConversationMessage.sent_at.asc(), ConversationMessage.id.asc())
        .all()
    ):
        latest_by_conversation[message.conversation_id] = message

    result = []
    for link in links:
        conversation = conversations_by_id.get(link.conversation_id)
        latest = latest_by_conversation.get(link.conversation_id)
        preview_source = (latest.body if latest is not None else None) or (
            conversation.preview_text if conversation else None
        )
        preview_text = " ".join((preview_source or "").split())[:200] or None
        result.append(
            TenantConversationVisibilityRead(
                conversation_id=link.conversation_id,
                tenant_id=tenant_id,
                is_visible=link.is_visible,
                subject=conversation.subject if conversation else None,
                matched_email=link.matched_email,
                last_message_at=conversation.last_message_at if conversation else None,
                preview_text=preview_text,
                last_message_direction=latest.direction if latest is not None else None,
                shared_with_other_tenants=link.conversation_id in shared_conversation_ids,
            )
        )
    return result


@router.patch("/tenants/{tenant_id}/conversations/{conversation_id}/visibility", response_model=TenantConversationVisibilityRead)
def update_tenant_conversation_visibility(
    tenant_id: int,
    conversation_id: int,
    payload: TenantConversationVisibilityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantConversationVisibilityRead:
    _get_tenant_or_404(db, tenant_id)
    link = (
        db.query(TenantConversationLink)
        .filter(
            TenantConversationLink.tenant_id == tenant_id,
            TenantConversationLink.conversation_id == conversation_id,
            TenantConversationLink.unlinked_at.is_(None),
        )
        .first()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active thread link not found")

    link.is_visible = payload.is_visible
    db.commit()
    db.refresh(link)

    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    shared_with_other_tenants = (
        db.query(TenantConversationLink)
        .filter(
            TenantConversationLink.conversation_id == conversation_id,
            TenantConversationLink.tenant_id != tenant_id,
            TenantConversationLink.unlinked_at.is_(None),
        )
        .first()
        is not None
    )

    logger.info(
        "tenant_conversation_visibility_updated tenant_id=%s conversation_id=%s is_visible=%s actor_user_id=%s",
        tenant_id,
        conversation_id,
        link.is_visible,
        current_user.id,
    )
    return TenantConversationVisibilityRead(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        is_visible=link.is_visible,
        subject=conversation.subject if conversation else None,
        matched_email=link.matched_email,
        last_message_at=conversation.last_message_at if conversation else None,
        shared_with_other_tenants=shared_with_other_tenants,
    )


@router.get("/tenants/{tenant_id}/auto-add-threads", response_model=TenantAutoAddThreadsRead)
def get_tenant_auto_add_threads(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantAutoAddThreadsRead:
    tenant = _get_tenant_or_404(db, tenant_id)
    return TenantAutoAddThreadsRead(tenant_id=tenant_id, auto_add=tenant.auto_add_shared_email_threads)


@router.patch("/tenants/{tenant_id}/auto-add-threads", response_model=TenantAutoAddThreadsRead)
def update_tenant_auto_add_threads(
    tenant_id: int,
    payload: TenantAutoAddThreadsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantAutoAddThreadsRead:
    tenant = _get_tenant_or_404(db, tenant_id)
    tenant.auto_add_shared_email_threads = payload.auto_add
    db.commit()

    logger.info(
        "tenant_auto_add_threads_updated tenant_id=%s auto_add=%s actor_user_id=%s",
        tenant_id,
        payload.auto_add,
        current_user.id,
    )
    return TenantAutoAddThreadsRead(tenant_id=tenant_id, auto_add=tenant.auto_add_shared_email_threads)
