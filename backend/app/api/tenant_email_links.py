import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.tenant import Tenant
from app.models.tenant_email_address import TenantEmailAddress
from app.models.user import User
from app.schemas.tenant_email_link import TenantEmailLinkCreate, TenantEmailLinkRead
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


@router.post("/tenants/{tenant_id}/email-links", response_model=TenantEmailLinkRead)
async def create_tenant_email_link(
    tenant_id: int,
    payload: TenantEmailLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantEmailLinkRead:
    tenant = _get_tenant_or_404(db, tenant_id)
    email = payload.email

    same_tenant_existing_link = (
        _active_email_links_query(db)
        .filter(TenantEmailAddress.tenant_id == tenant_id, TenantEmailAddress.email == email)
        .first()
    )
    if same_tenant_existing_link is not None:
        return same_tenant_existing_link

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

    logger.info(
        "tenant_email_link_created tenant_id=%s email=%s beds24_sync_status=%s actor_user_id=%s",
        tenant_id,
        email,
        new_link.beds24_sync_status,
        current_user.id,
    )
    return new_link


@router.delete("/tenants/{tenant_id}/email-links/{link_id}", response_model=TenantEmailLinkRead)
async def delete_tenant_email_link(
    tenant_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantEmailLinkRead:
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

    db.commit()
    db.refresh(link)

    logger.info(
        "tenant_email_link_unlinked tenant_id=%s link_id=%s actor_user_id=%s",
        tenant_id,
        link_id,
        current_user.id,
    )
    return link
