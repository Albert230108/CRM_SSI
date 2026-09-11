import re
from typing import Callable

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.tenant_email_address import TenantEmailAddress
from app.services.datetime_placeholders import resolve_datetime_placeholders

# Curated set of Tenant fields exposed as {{placeholder}} tokens in email templates.
# Financial fields (total_price, commission, deposit) are deliberately excluded since
# template output can be forwarded to an external address.
PLACEHOLDER_FIELDS: dict[str, Callable[[Tenant], object]] = {
    "tenant_name": lambda t: t.name,
    "first_name": lambda t: t.first_name,
    "last_name": lambda t: t.last_name,
    "email": lambda t: t.email,
    "phone": lambda t: t.phone,
    "check_in": lambda t: t.check_in,
    "check_out": lambda t: t.check_out,
    "num_nights": lambda t: t.num_nights,
    "num_adults": lambda t: t.num_adults,
    "num_children": lambda t: t.num_children,
    "room_name": lambda t: t.room_name,
    "property_name": lambda t: t.property_name,
    "booking_id": lambda t: t.booking_id,
    "booking_status": lambda t: t.booking_status,
    "language": lambda t: t.language,
    "arrival_time": lambda t: t.arrival_time,
    "departure_time": lambda t: t.departure_time,
    "city": lambda t: t.city,
    "country": lambda t: t.country,
}

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _primary_active_email(db: Session, tenant_id: int) -> str | None:
    """The tenant's first active CRM_EMAIL link, mirroring gmail_integration._primary_linked_email."""
    return (
        db.query(TenantEmailAddress.email)
        .filter(TenantEmailAddress.tenant_id == tenant_id, TenantEmailAddress.is_active.is_(True))
        .order_by(TenantEmailAddress.id.asc())
        .limit(1)
        .scalar()
    )


def resolve_template_text(text: str, tenant: Tenant, db: Session | None = None) -> str:
    """Replace {{placeholder}} tokens with tenant field values. Unknown tokens are left as-is.

    Tenant.email is rarely populated by the Beds24 sync (which writes CRM_EMAIL links to
    TenantEmailAddress instead), so {{email}} falls back to the tenant's primary active
    linked address when a db session is available.
    """
    text = resolve_datetime_placeholders(text)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        getter = PLACEHOLDER_FIELDS.get(key)
        if getter is None:
            return match.group(0)
        value = getter(tenant)
        if key == "email" and not value and db is not None:
            value = _primary_active_email(db, tenant.id)
        return str(value) if value is not None else ""

    return _PLACEHOLDER_PATTERN.sub(_replace, text)
