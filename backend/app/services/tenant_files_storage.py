"""Read-only access to the local tenant-files tree for the CRM backend.

Rooted at TENANT_FILES_ROOT - the same mounted Tenants/ folder tree the Quotation Manager's
tenant_files.py already writes quotation PDFs into (see quotation-manager/backend/app/services/
tenant_files.py, which this module's naming helpers deliberately mirror so both services agree on
where a given booking's files live: {root}/{year}/{booking_id}_{first}_{last}/).

This module only ever reads: it lists a tenant's folder, resolves a single file for download, and
walks the whole tree for the cross-tenant search the Quotation Manager's Files page uses. Nothing
here writes - PDF generation/writing stays exactly where it is (the quotation-manager service).
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, status

# Read lazily (not a module constant) so tests can monkeypatch/setenv before any call, the same
# pattern attachment_storage.py uses for ATTACHMENTS_ROOT.
def _root() -> pathlib.Path:
    value = os.getenv("TENANT_FILES_ROOT", "").strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TENANT_FILES_ROOT is not configured")
    return pathlib.Path(value)


def _not_writable_error() -> HTTPException:
    """A write into the tenant files tree failed at the OS level - almost always because the
    volume is mounted read-only or the process lacks permission. Surface a clean 503 rather than a
    raw 500 so the cause (a deploy/mount misconfig) is obvious."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Tenant files storage is not writable (check the TENANT_FILES_ROOT mount is read-write)",
    )


def _safe_name_component(value: str) -> str:
    # Matches quotation-manager/backend/app/services/tenant_files.py's _safe_name_component
    # exactly - both services must agree on the folder name a given tenant maps to.
    return "".join(c for c in (value or "") if c.isalnum() or c in (" ", "-", "_")).rstrip()


@dataclass
class FileEntry:
    name: str
    kind: str  # "file" | "directory"
    size: int | None
    # Path relative to TENANT_FILES_ROOT, e.g. "2026/12345_John_Doe/Quotation_....pdf" - what
    # download/resolve_download_path expects back.
    relative_path: str


def tenant_booking_folder_name(booking_id: str, first_name: str | None, last_name: str | None) -> str:
    """The canonical `{booking_id}_{first}_{last}` folder name for a tenant. This is the single
    source of truth for tenant folder naming: the server-tree storage here, the OneDrive path
    builders (onedrive_service / tenants._build_one_drive_folder_path), and the QM tenant_files
    service all go through it so a tenant always maps to the same folder in every store. Name
    components keep spaces and hyphens and strip other punctuation (see _safe_name_component)."""
    safe_first = _safe_name_component(first_name or "")
    safe_last = _safe_name_component(last_name or "")
    return f"{booking_id}_{safe_first}_{safe_last}"


def booking_folder_relative_path(booking_id: str, first_name: str | None, last_name: str | None, year: int) -> pathlib.PurePosixPath:
    return pathlib.PurePosixPath(str(year)) / tenant_booking_folder_name(booking_id, first_name, last_name)


def _year_from_check_in(check_in: str | None) -> int:
    if check_in:
        try:
            return datetime.strptime(check_in, "%Y-%m-%d").year
        except ValueError:
            pass
    return datetime.now().year


def list_tenant_folder(*, booking_id: str, first_name: str | None, last_name: str | None, check_in: str | None) -> dict:
    """Lists a single tenant's booking folder. A tenant with no quotation on disk yet is not an
    error - it just comes back with an empty item list, matching how a brand-new booking has no
    folder until the first PDF is generated."""
    if not booking_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant has no booking id")

    root = _root()
    relative = booking_folder_relative_path(booking_id, first_name, last_name, _year_from_check_in(check_in))
    folder = root / relative
    items: list[FileEntry] = []
    if folder.is_dir():
        for entry in sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if entry.is_dir() and entry.name.startswith("_"):
                continue  # hide internal subfolders (e.g. _local_quotes) from the files list
            items.append(
                FileEntry(
                    name=entry.name,
                    kind="directory" if entry.is_dir() else "file",
                    size=entry.stat().st_size if entry.is_file() else None,
                    relative_path=str(relative / entry.name),
                )
            )
    return {"folder_path": str(relative), "items": items}


def save_tenant_file(
    *,
    booking_id: str,
    first_name: str | None,
    last_name: str | None,
    check_in: str | None,
    filename: str,
    content: bytes,
) -> FileEntry:
    """Writes an uploaded file into a tenant's booking folder under TENANT_FILES_ROOT, creating
    the folder on first upload. The stored name is sanitized with the same rules as the folder
    components, and a collision is de-duplicated ("name.pdf" -> "name (1).pdf") so an upload never
    silently overwrites an existing file. Returns the created FileEntry."""
    if not booking_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant has no booking id")

    safe_name = _safe_upload_filename(filename)
    if not safe_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file name")

    root = _root()
    relative = booking_folder_relative_path(booking_id, first_name, last_name, _year_from_check_in(check_in))
    folder = (root / relative)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = _dedupe_path(folder / safe_name)
        target.write_bytes(content)
    except OSError as exc:
        raise _not_writable_error() from exc
    return FileEntry(
        name=target.name,
        kind="file",
        size=target.stat().st_size,
        relative_path=str(relative / target.name),
    )


def _safe_upload_filename(filename: str) -> str:
    """Sanitize an uploaded file name: keep the extension, apply the same character allow-list as
    the folder components to the stem, and never let path separators through."""
    raw = pathlib.PurePosixPath((filename or "").replace("\\", "/")).name
    stem = pathlib.PurePosixPath(raw).stem
    suffix = pathlib.PurePosixPath(raw).suffix
    safe_stem = _safe_name_component(stem).strip() or "file"
    safe_suffix = "".join(c for c in suffix if c.isalnum() or c == ".")
    return f"{safe_stem}{safe_suffix}"


def _dedupe_path(path: pathlib.Path) -> pathlib.Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for n in range(1, 1000):
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Too many files with the same name")


import json

# Local quote drafts (Quotation Manager) live in a hidden subfolder of the tenant booking folder,
# separate from the generated PDFs, so listing PDFs never surfaces them.
_QUOTES_SUBDIR = "_local_quotes"


def _quotes_dir(booking_id: str, first_name: str | None, last_name: str | None, check_in: str | None) -> pathlib.Path:
    if not booking_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant has no booking id")
    relative = booking_folder_relative_path(booking_id, first_name, last_name, _year_from_check_in(check_in))
    return _root() / relative / _QUOTES_SUBDIR


def save_local_quote(
    *, booking_id: str, first_name: str | None, last_name: str | None, check_in: str | None, name: str, snapshot: dict
) -> str:
    """Save a named local quote draft (a JSON snapshot of the editor state) under the tenant's
    booking folder, without touching Beds24. Overwrites a same-named quote. Returns the stored name."""
    safe_name = _safe_name_component(name).strip()
    if not safe_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A quote name is required")
    folder = _quotes_dir(booking_id, first_name, last_name, check_in)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{safe_name}.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except OSError as exc:
        raise _not_writable_error() from exc
    return safe_name


def list_local_quotes(*, booking_id: str, first_name: str | None, last_name: str | None, check_in: str | None) -> list[dict]:
    """List saved local quotes (name + last-modified) for a booking, newest first."""
    folder = _quotes_dir(booking_id, first_name, last_name, check_in)
    if not folder.is_dir():
        return []
    quotes = [
        {"name": f.stem, "updated_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
        for f in folder.glob("*.json")
        if f.is_file()
    ]
    return sorted(quotes, key=lambda q: q["updated_at"], reverse=True)


def load_local_quote(*, booking_id: str, first_name: str | None, last_name: str | None, check_in: str | None, name: str) -> dict:
    """Load a named local quote snapshot. 404s if it doesn't exist."""
    safe_name = _safe_name_component(name).strip()
    folder = _quotes_dir(booking_id, first_name, last_name, check_in)
    path = folder / f"{safe_name}.json"
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local quote not found")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_download_path(relative_path: str) -> pathlib.Path:
    """Resolves a relative_path (as returned by list_tenant_folder/search) to an absolute path
    under TENANT_FILES_ROOT, refusing anything that would escape it."""
    root = _root().resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return candidate


def search_tenant_files(
    *,
    q: str | None = None,
    booking_id: str | None = None,
    year: int | None = None,
    tenant_name: str | None = None,
    room: str | None = None,
    limit: int = 200,
) -> list[FileEntry]:
    """Walks the whole TENANT_FILES_ROOT tree ({year}/{booking}_{first}_{last}/{files}) and
    returns files matching every filter given (all optional, all case-insensitive substring
    matches except `year`, which is exact and `booking_id`, matched against the folder's
    "{booking_id}_" prefix). Used by the Quotation Manager's cross-tenant Files page - there is no
    index, this scans the tree at query time, which is fine at this portfolio's scale.
    """
    root = _root()
    if not root.is_dir():
        return []

    q_lower = (q or "").strip().lower()
    tenant_name_lower = (tenant_name or "").strip().lower()
    room_lower = (room or "").strip().lower()
    booking_prefix = f"{booking_id}_" if booking_id else None

    results: list[FileEntry] = []
    year_dirs = sorted(root.iterdir(), key=lambda p: p.name, reverse=True) if root.is_dir() else []
    for year_dir in year_dirs:
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        if year is not None and int(year_dir.name) != year:
            continue
        for booking_dir in sorted(year_dir.iterdir(), key=lambda p: p.name):
            if not booking_dir.is_dir():
                continue
            if booking_prefix and not booking_dir.name.startswith(booking_prefix):
                continue
            if tenant_name_lower and tenant_name_lower not in booking_dir.name.lower():
                continue
            for file_path in sorted(booking_dir.iterdir(), key=lambda p: p.name):
                if not file_path.is_file():
                    continue
                name_lower = file_path.name.lower()
                if room_lower and room_lower not in name_lower:
                    continue
                if q_lower and q_lower not in name_lower and q_lower not in booking_dir.name.lower():
                    continue
                results.append(
                    FileEntry(
                        name=file_path.name,
                        kind="file",
                        size=file_path.stat().st_size,
                        relative_path=str(pathlib.PurePosixPath(year_dir.name) / booking_dir.name / file_path.name),
                    )
                )
                if len(results) >= limit:
                    return results
    return results
