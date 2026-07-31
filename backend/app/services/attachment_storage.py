"""
Blob storage for email/WhatsApp attachments, rooted at ATTACHMENTS_ROOT (a mounted
volume, separate from the quotation-manager's TENANT_FILES_ROOT - this stores
communication attachments, not booking documents).

Layout: {ATTACHMENTS_ROOT}/{tenant_id}/{YYYY}/{MM}/{uuid4().hex}{ext}

Unlike tenant_files.py, the on-disk filename never contains user input - the
original filename is stored only in the communication_attachments.filename column.
That makes path traversal structurally impossible rather than filter-dependent;
_safe_name_component below is used only to sanitize what we echo back in a
Content-Disposition header, not anything that touches the filesystem.
"""

import hashlib
import os
import pathlib
import re
import uuid
from datetime import datetime, timezone
from typing import NamedTuple

_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


class AttachmentStorageError(Exception):
    """Raised for storage-layer failures: bad storage key, filesystem error, oversize file."""
    pass


class AttachmentTooLargeError(AttachmentStorageError):
    pass


def _root() -> pathlib.Path:
    # Read lazily (not a module constant) so tests can repoint ATTACHMENTS_ROOT via
    # monkeypatch/setenv before any call, rather than at import time.
    return pathlib.Path(os.getenv("ATTACHMENTS_ROOT", "/app/attachments"))


def max_file_bytes() -> int:
    return int(os.getenv("ATTACHMENT_MAX_FILE_BYTES", str(10 * 1024 * 1024)))


def max_message_bytes(channel: str) -> int:
    if channel == "email":
        return int(os.getenv("ATTACHMENT_MAX_EMAIL_MESSAGE_BYTES", str(20 * 1024 * 1024)))
    return int(os.getenv("ATTACHMENT_MAX_MESSAGE_BYTES", str(25 * 1024 * 1024)))


def _safe_name_component(value: str) -> str:
    return "".join(c for c in value if c.isalnum() or c in (" ", "-", "_", ".")).strip() or "attachment"


class StoredBlob(NamedTuple):
    storage_key: str
    size_bytes: int
    sha256: str


def save_bytes(tenant_id: int, data: bytes, filename: str) -> StoredBlob:
    if len(data) > max_file_bytes():
        raise AttachmentTooLargeError(f"File exceeds the {max_file_bytes()} byte limit")

    ext = pathlib.PurePosixPath(filename or "").suffix
    if not _EXT_RE.match(ext):
        ext = ""

    now = datetime.now(timezone.utc)
    relative_dir = pathlib.PurePosixPath(str(tenant_id)) / f"{now:%Y}" / f"{now:%m}"
    target_dir = _root() / relative_dir
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AttachmentStorageError(f"Could not create attachment directory: {exc}") from exc

    disk_name = f"{uuid.uuid4().hex}{ext}"
    storage_key = str(relative_dir / disk_name)
    target_path = _root() / storage_key

    try:
        target_path.write_bytes(data)
    except OSError as exc:
        raise AttachmentStorageError(f"Could not write attachment: {exc}") from exc

    return StoredBlob(storage_key=storage_key, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def resolve_path(storage_key: str) -> pathlib.Path:
    root = _root().resolve()
    candidate = (root / storage_key).resolve()
    if not candidate.is_relative_to(root):
        raise AttachmentStorageError(f"Refusing to resolve storage key outside root: {storage_key!r}")
    return candidate


def read_bytes(storage_key: str) -> bytes:
    path = resolve_path(storage_key)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AttachmentStorageError(f"Could not read attachment '{storage_key}': {exc}") from exc


def guess_mime(filename: str, declared: str | None) -> str:
    if declared:
        return declared
    import mimetypes

    guessed, _ = mimetypes.guess_type(filename or "")
    return guessed or "application/octet-stream"


def content_disposition_filename(filename: str) -> str:
    return _safe_name_component(filename)
