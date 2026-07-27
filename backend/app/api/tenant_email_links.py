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
from app.schemas.tenant_email_link import TenantEmailLinkCreate, TenantEmailLinkCreateRead, TenantEmailLinkDeleteRead, TenantEmailLinkRead
from app.services.background_jobs import start_job
from app.services.beds24_client import BEDS24_EMAIL_INFO_CODE, add_booking_info_item, delete_booking_info_item, get_booking_info_items

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

    # Push to Beds24 so the CRM link and the booking's info items stay consistent. A failure here
    # does not undo the CRM-side link — it's recorded via beds24_sync_status so it can be retried,
    # since the CRM link is still useful (e.g. for Gmail matching) even if Beds24 is unreachable.
    try:
        info_item = await add_booking_info_item(tenant.booking_id, BEDS24_EMAIL_INFO_CODE, email)
        new_link.beds24_info_item_id = str(info_item["id"]) if info_item and info_item.get("id") is not None else None
        new_link.beds24_sync_status = "synced" if info_item else "failed"
    except HTTPException as exc:
        logger.warning(
            "tenant_email_link_beds24_sync_failed tenant_id=%s email=%s error=%s",
            tenant_id,
            email,
            exc.detail,
        )
        new_link.beds24_sync_status = "failed"
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


def _remove_conversations_for_matched_email(db: Session, tenant_id: int, email: str) -> tuple[int, int]:
    """Hard-delete every conversation this tenant's link to `email` matched, since unlinking an
    email means its message history should no longer be attached to this tenant. A conversation
    also linked to a *different* tenant is left alone (only this tenant's link is removed) --
    deleting it would erase that other tenant's history too. Returns
    (conversations_deleted, conversations_only_unlinked).
    """
    now = datetime.now(timezone.utc)
    conversation_links = (
        db.query(TenantConversationLink)
        .filter(
            TenantConversationLink.tenant_id == tenant_id,
            TenantConversationLink.matched_email == email,
            TenantConversationLink.unlinked_at.is_(None),
        )
        .all()
    )

    deleted = 0
    unlinked_shared = 0
    for conversation_link in conversation_links:
        conversation_id = conversation_link.conversation_id
        other_tenant_has_active_link = (
            db.query(TenantConversationLink)
            .filter(
                TenantConversationLink.conversation_id == conversation_id,
                TenantConversationLink.tenant_id != tenant_id,
                TenantConversationLink.unlinked_at.is_(None),
            )
            .first()
            is not None
        )
        if other_tenant_has_active_link:
            conversation_link.unlinked_at = now
            unlinked_shared += 1
            continue

        db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).delete(synchronize_session=False)
        db.query(TenantConversationLink).filter(TenantConversationLink.conversation_id == conversation_id).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.id == conversation_id).delete(synchronize_session=False)
        deleted += 1

    return deleted, unlinked_shared


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

    deleted_conversations, shared_conversations_unlinked = _remove_conversations_for_matched_email(db, tenant_id, link.email)

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
