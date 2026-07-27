from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.tenant_email_address import TenantEmailAddress
from app.services.beds24_client import BEDS24_EMAIL_INFO_CODE

BEDS24_LINK_SOURCE = "beds24"


def sync_tenant_email_addresses_from_beds24(db: Session, tenant: Tenant, info_items: list[dict[str, Any]]) -> None:
    """Reconcile this tenant's linked emails against the booking's current Beds24 info items.

    Beds24 is treated as authoritative for its own CRM_EMAIL info items: an item present there
    but missing here gets linked (even if the email is already linked to a different tenant --
    same "warn but allow" spirit as manual linking, but there's no UI to confirm from a
    webhook). An item that disappears from Beds24 gets unlinked here too, but only for links we
    know were actually confirmed there (has a beds24_info_item_id) -- a link still pending sync
    isn't touched, since we never confirmed it existed in Beds24 in the first place.
    """
    current_ids_by_email: dict[str, str] = {}
    for item in info_items:
        if not isinstance(item, dict) or item.get("code") != BEDS24_EMAIL_INFO_CODE:
            continue
        email = str(item.get("text") or "").strip().lower()
        info_item_id = item.get("id")
        if email and info_item_id is not None:
            current_ids_by_email[email] = str(info_item_id)

    active_links = (
        db.query(TenantEmailAddress)
        .filter(TenantEmailAddress.tenant_id == tenant.id, TenantEmailAddress.is_active.is_(True))
        .all()
    )
    existing_by_email = {link.email: link for link in active_links}
    now = datetime.now(timezone.utc)

    for link in active_links:
        if link.beds24_info_item_id and current_ids_by_email.get(link.email) != link.beds24_info_item_id:
            link.is_active = False
            link.unlinked_at = now
            link.beds24_sync_status = "synced"

    for email, info_item_id in current_ids_by_email.items():
        existing = existing_by_email.get(email)
        if existing is not None:
            if not existing.beds24_info_item_id:
                existing.beds24_info_item_id = info_item_id
                existing.beds24_sync_status = "synced"
            continue
        db.add(
            TenantEmailAddress(
                tenant_id=tenant.id,
                email=email,
                beds24_info_item_id=info_item_id,
                beds24_sync_status="synced",
                source=BEDS24_LINK_SOURCE,
                is_active=True,
            )
        )
