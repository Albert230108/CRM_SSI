from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.tenant_notes_history import TenantNotesHistory

SOURCE_MANUAL = "manual"
SOURCE_BEDS24_WEBHOOK = "beds24_webhook"
SOURCE_BEDS24_SYNC_ALL = "beds24_sync_all"
SOURCE_BEDS24_SYNC_SERVICE = "beds24_sync_service"
SOURCE_BEDS24_IMPORT = "beds24_import"


def set_tenant_notes(
    db: Session,
    tenant: Tenant,
    new_value: str | None,
    source: str,
    changed_by_user_id: int | None = None,
) -> None:
    """Update tenant.notes and record the change in tenant_notes_history.

    Skips writing a history row when the value doesn't actually change, since
    Beds24 sync paths re-apply the same notes value on every sync and that
    would otherwise flood the history with no-op entries.
    """
    old_value = tenant.notes
    if old_value == new_value:
        return
    tenant.notes = new_value
    db.add(TenantNotesHistory(
        tenant_id=tenant.id,
        old_value=old_value,
        new_value=new_value,
        source=source,
        changed_by_user_id=changed_by_user_id,
    ))
