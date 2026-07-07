from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

_DIGIT_RE = re.compile(r"\d+")


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value).strip() or None
    return None


def normalize_whatsapp_phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(_DIGIT_RE.findall(str(value)))
    return digits or None


def normalize_whatsapp_chat_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


@dataclass(frozen=True)
class WhatsAppIdentity:
    raw_chat_id: str | None
    normalized_phone: str | None
    canonical_chat_id: str | None
    is_group: bool


def get_canonical_whatsapp_identity(
    payload: dict[str, Any] | None = None,
    *,
    direction: str | None = None,
    raw_chat_id: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    sender_normalized: str | None = None,
    recipient_normalized: str | None = None,
    whatsapp_chat_id: str | None = None,
    whatsapp_normalized_phone: str | None = None,
    whatsapp_identity_key: str | None = None,
    is_group: bool | None = None,
) -> WhatsAppIdentity:
    source = payload or {}
    raw_identity = normalize_whatsapp_chat_id(
        _first_non_empty(
            raw_chat_id,
            whatsapp_chat_id,
            source.get("whatsapp_raw_chat_id"),
            source.get("whatsapp_chat_id"),
            source.get("external_chat_namespace"),
        )
    )

    resolved_direction = (direction or _first_non_empty(source.get("direction")) or "").strip().lower()
    resolved_sender = _first_non_empty(sender, source.get("sender"), source.get("from"), source.get("author"), source.get("sender_raw"))
    resolved_recipient = _first_non_empty(recipient, source.get("recipient"), source.get("to"))
    resolved_sender_normalized = _first_non_empty(sender_normalized, source.get("sender_normalized"))
    resolved_recipient_normalized = _first_non_empty(recipient_normalized, source.get("recipient_normalized"))
    resolved_phone = normalize_whatsapp_phone(
        _first_non_empty(
            whatsapp_normalized_phone,
            source.get("whatsapp_normalized_phone"),
            source.get("sender_normalized"),
            source.get("recipient_normalized"),
            resolved_sender_normalized if resolved_direction != "outbound" else None,
            resolved_recipient_normalized if resolved_direction == "outbound" else None,
            resolved_sender if resolved_direction != "outbound" else None,
            resolved_recipient if resolved_direction == "outbound" else None,
            source.get("wa_id"),
            source.get("phone_number"),
        )
    )

    resolved_is_group = bool(
        is_group
        if is_group is not None
        else source.get("is_group")
        if source.get("is_group") is not None
        else raw_identity and raw_identity.endswith("@g.us")
    )

    canonical_chat_id = normalize_whatsapp_chat_id(
        _first_non_empty(
            whatsapp_identity_key,
            source.get("whatsapp_identity_key"),
            resolved_phone if not resolved_is_group else None,
            raw_identity,
        )
    )
    if resolved_is_group and raw_identity:
        canonical_chat_id = raw_identity

    return WhatsAppIdentity(
        raw_chat_id=raw_identity,
        normalized_phone=resolved_phone,
        canonical_chat_id=canonical_chat_id,
        is_group=resolved_is_group,
    )
