from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re

_DIGIT_RE = re.compile(r"\d+")


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value).strip() or None
    return None


def normalize_whatsapp_phone(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if lowered.endswith("@c.us"):
        normalized = lowered.split("@", 1)[0]
    elif "@" in lowered:
        return None
    digits = "".join(_DIGIT_RE.findall(normalized))
    if len(digits) < 7:
        return None
    if set(digits) == {"0"}:
        return None
    return digits


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


def _is_person_like_phone(value: str | None) -> bool:
    return normalize_whatsapp_phone(value) is not None


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
    resolved_is_group = bool(
        is_group
        if is_group is not None
        else source.get("is_group")
        if source.get("is_group") is not None
        else raw_identity and raw_identity.endswith("@g.us")
    )

    trusted_phone = normalize_whatsapp_phone(
        _first_non_empty(
            whatsapp_normalized_phone,
            source.get("whatsapp_normalized_phone"),
            sender_normalized,
            source.get("sender_normalized"),
            recipient_normalized,
            source.get("recipient_normalized"),
            source.get("wa_id"),
            source.get("phone_number"),
            raw_chat_id,
            whatsapp_chat_id,
            source.get("recipient") if resolved_direction == "outbound" else None,
            recipient if resolved_direction == "outbound" else None,
        )
    )

    candidate_identity = normalize_whatsapp_chat_id(
        _first_non_empty(
            whatsapp_identity_key,
            source.get("whatsapp_identity_key"),
        )
    )

    if resolved_is_group and raw_identity:
        canonical_chat_id = raw_identity
    elif trusted_phone:
        canonical_chat_id = trusted_phone
    elif candidate_identity:
        canonical_chat_id = candidate_identity
    else:
        canonical_chat_id = raw_identity

    if canonical_chat_id and canonical_chat_id.endswith("@g.us"):
        resolved_is_group = True

    return WhatsAppIdentity(
        raw_chat_id=raw_identity,
        normalized_phone=trusted_phone,
        canonical_chat_id=canonical_chat_id,
        is_group=resolved_is_group,
    )
