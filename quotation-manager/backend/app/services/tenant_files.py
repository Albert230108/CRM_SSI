"""
Tenant folder + quotation-file naming logic, ported from the desktop
Quotation Manager (Python-EmailQuotation-1/src/interface.py's
create_booking_folder, and the glob-based auto-numbering that lived inline
inside functions.create_invoice_pdf). Rooted at TENANT_FILES_ROOT (a mounted
volume pointing at the same OneDrive Tenants/ folder tree the desktop app
already writes into), instead of a path relative to this file.
"""

import glob
import os
import pathlib
from datetime import datetime
from typing import NamedTuple

from app.config import TENANT_FILES_ROOT

TENANT_FILES_ROOT_PATH = pathlib.Path(TENANT_FILES_ROOT)


class TenantFolderError(Exception):
    """Raised when the booking folder can't be created (bad date, filesystem error)."""
    pass


def _safe_name_component(value: str) -> str:
    return "".join(c for c in value if c.isalnum() or c in (' ', '-', '_')).rstrip()


def create_booking_folder(booking_id: str, first_name: str, last_name: str, arrival_date_str: str) -> pathlib.Path:
    """
    Create (if needed) and return the per-booking folder: Tenants/{year}/{booking_id}_{first}_{last}/

    Args:
        booking_id: Beds24 booking id
        first_name: Guest first name
        last_name: Guest last name
        arrival_date_str: Check-in date, "YYYY-MM-DD"

    Returns:
        Path to the (now-existing) booking folder.
    """
    try:
        arrival_dt = datetime.strptime(arrival_date_str, "%Y-%m-%d")
    except ValueError as exc:
        raise TenantFolderError(f"Invalid arrival date '{arrival_date_str}': {exc}") from exc

    year = str(arrival_dt.year)
    year_folder_path = TENANT_FILES_ROOT_PATH / year

    safe_first = _safe_name_component(first_name or "")
    safe_last = _safe_name_component(last_name or "")
    folder_name = f"{booking_id}_{safe_first}_{safe_last}"
    booking_folder_path = year_folder_path / folder_name

    try:
        booking_folder_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TenantFolderError(f"Could not create booking folder '{booking_folder_path}': {exc}") from exc

    return booking_folder_path


class NextQuotationOutput(NamedTuple):
    path: pathlib.Path
    quotation_number: int


def next_quotation_output_path(
    folder: pathlib.Path,
    booking_id: str,
    room_label: str,
    tenant_name: str,
    checkin_date_str: str | None,
    checkout_date_str: str | None,
) -> NextQuotationOutput:
    """
    Compute the next auto-incrementing quotation PDF path in `folder`, matching
    the desktop app's naming convention and glob-based numbering exactly:
    Quotation_{booking_id}_{NNN} - {room_label} - {tenant_name} - (DD Mon YYYY~DD Mon YYYY).pdf
    """
    existing_files = glob.glob(os.path.join(str(folder), f"Quotation_{booking_id}_*.pdf"))
    quotation_number = len(existing_files) + 1

    safe_room_label = _safe_name_component(room_label or "Unknown")[:20]
    safe_tenant_name = _safe_name_component(tenant_name or "Unknown")[:20]

    def _format_date(date_str: str | None) -> str:
        if not date_str:
            return "Unknown"
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            return "Unknown"

    safe_checkin = _format_date(checkin_date_str)
    safe_checkout = _format_date(checkout_date_str)

    def _build_path(number: int) -> pathlib.Path:
        filename = (
            f"Quotation_{booking_id}_{number:03d} - {safe_room_label} - "
            f"{safe_tenant_name} - ({safe_checkin}~{safe_checkout}).pdf"
        )
        return folder / filename

    output_path = _build_path(quotation_number)
    while output_path.exists():
        quotation_number += 1
        output_path = _build_path(quotation_number)

    return NextQuotationOutput(path=output_path, quotation_number=quotation_number)
