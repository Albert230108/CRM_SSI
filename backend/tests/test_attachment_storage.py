import os

import pytest

from app.services import attachment_storage


@pytest.fixture(autouse=True)
def attachments_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_ROOT", str(tmp_path))
    yield tmp_path


def test_save_and_read_round_trip():
    data = b"hello world"
    blob = attachment_storage.save_bytes(1, data, "notes.txt")
    assert blob.size_bytes == len(data)
    assert attachment_storage.read_bytes(blob.storage_key) == data
    assert blob.storage_key.startswith("1/")
    assert blob.storage_key.endswith(".txt")


def test_sha256_is_deterministic_for_same_content():
    blob1 = attachment_storage.save_bytes(1, b"same content", "a.txt")
    blob2 = attachment_storage.save_bytes(1, b"same content", "b.txt")
    assert blob1.sha256 == blob2.sha256
    assert blob1.storage_key != blob2.storage_key


def test_oversize_file_rejected(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_MAX_FILE_BYTES", "10")
    with pytest.raises(attachment_storage.AttachmentTooLargeError):
        attachment_storage.save_bytes(1, b"x" * 11, "big.bin")


def test_extension_whitelist_strips_unsafe_extension():
    blob = attachment_storage.save_bytes(1, b"data", "evil.sh; rm -rf")
    assert not blob.storage_key.endswith("; rm -rf")


@pytest.mark.parametrize(
    "storage_key",
    ["../../etc/passwd", "/etc/passwd", "1/2026/07/../../../../etc/passwd"],
)
def test_resolve_path_rejects_traversal(storage_key):
    with pytest.raises(attachment_storage.AttachmentStorageError):
        attachment_storage.resolve_path(storage_key)


def test_resolve_path_accepts_valid_key(tmp_path):
    blob = attachment_storage.save_bytes(2, b"data", "file.pdf")
    resolved = attachment_storage.resolve_path(blob.storage_key)
    assert resolved.is_file()
    assert str(resolved).startswith(str(tmp_path))


def test_content_disposition_filename_strips_hostile_characters():
    safe = attachment_storage.content_disposition_filename('../../etc/passwd"; evil')
    assert "/" not in safe
    assert '"' not in safe


def test_guess_mime_uses_declared_then_falls_back():
    assert attachment_storage.guess_mime("a.pdf", "application/custom") == "application/custom"
    assert attachment_storage.guess_mime("a.pdf", None) == "application/pdf"
    assert attachment_storage.guess_mime("noext", None) == "application/octet-stream"
