from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant

PROVIDER_GMAIL = "gmail"


class TimelineMessageRead(BaseModel):
    id: int
    provider: str
    provider_message_id: str
    direction: str
    sender_email: str | None = None
    recipient_email: str | None = None
    subject: str | None = None
    body: str
    sent_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TimelineWhatsappMessageRead(BaseModel):
    id: int
    tenant_id: int
    channel: str
    direction: str
    provider: str | None = None
    external_account_id: str | None = None
    external_phone_id: str | None = None
    external_chat_namespace: str | None = None
    whatsapp_chat_id: str | None = None
    whatsapp_identity_key: str | None = None
    whatsapp_normalized_phone: str | None = None
    provider_message_id: str | None = None
    subject: str | None = None
    message: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TimelineWhatsappBlockRead(BaseModel):
    block_id: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    messages: list[TimelineWhatsappMessageRead]
    message_count: int


class TimelineEmailThreadRead(BaseModel):
    type: str = "email_thread"
    thread_id: int
    provider_thread_id: str
    provider_account_id: int | None = None
    provider_account_email: str | None = None
    provider_account_display_name: str | None = None
    subject: str | None = None
    preview_text: str | None = None
    anchor_timestamp: datetime
    messages: list[TimelineMessageRead]
    whatsapp_blocks: list[TimelineWhatsappBlockRead]


class TimelineWhatsappGroupRead(BaseModel):
    type: str = "whatsapp_group"
    group_id: str
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None
    messages: list[TimelineWhatsappMessageRead]
    message_count: int


class MixedTimelineRead(BaseModel):
    tenant_id: int
    tenant_name: str
    items: list[TimelineEmailThreadRead | TimelineWhatsappGroupRead]


@dataclass(frozen=True)
class _EmailThreadWindow:
    thread: Conversation
    anchor_timestamp: datetime


def _ensure_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _thread_message_sort_key(message: ConversationMessage) -> tuple[datetime, int]:
    return (_ensure_utc(message.sent_at), int(message.id))


def _communication_sort_key(message: Communication) -> tuple[datetime, int]:
    return (_ensure_utc(message.created_at), int(message.id))


def _load_tenant_conversations(db: Session, tenant_id: int) -> list[Conversation]:
    conversations = (
        db.query(Conversation)
        .filter(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.id.desc())
        .all()
    )
    account_lookup = {account.id: account for account in db.query(GmailAccount).all()}
    result: list[Conversation] = []
    for conversation in conversations:
        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.sent_at.asc(), ConversationMessage.id.asc())
            .all()
        )
        mailbox = account_lookup.get(conversation.provider_account_id)
        setattr(conversation, "messages", messages)
        setattr(conversation, "provider_account_email", mailbox.email_address if mailbox else None)
        setattr(conversation, "provider_account_display_name", mailbox.display_name if mailbox else None)
        result.append(conversation)
    return result


def _load_tenant_whatsapp(db: Session, tenant_id: int) -> list[Communication]:
    return (
        db.query(Communication)
        .filter(Communication.tenant_id == tenant_id)
        .filter(Communication.channel == "whatsapp")
        .order_by(Communication.created_at.asc(), Communication.id.asc())
        .all()
    )


def _build_thread_windows(conversations: Iterable[Conversation]) -> list[_EmailThreadWindow]:
    windows: list[_EmailThreadWindow] = []
    for thread in conversations:
        messages = sorted(thread.messages or [], key=_thread_message_sort_key)
        if not messages:
            continue
        anchor_timestamp = _ensure_utc(messages[-1].sent_at)
        windows.append(_EmailThreadWindow(thread=thread, anchor_timestamp=anchor_timestamp))
    windows.sort(key=lambda item: (item.anchor_timestamp, item.thread.id))
    return windows


def _build_whatsapp_group_id(prefix: str, start: datetime | None, end: datetime | None, count: int) -> str:
    start_key = start.isoformat() if start else "none"
    end_key = end.isoformat() if end else "none"
    return f"{prefix}:{start_key}:{end_key}:{count}"


def _build_whatsapp_block_id(thread_id: int, index: int, start: datetime | None, end: datetime | None, count: int) -> str:
    start_key = start.isoformat() if start else "none"
    end_key = end.isoformat() if end else "none"
    return f"thread-{thread_id}:whatsapp-{index}:{start_key}:{end_key}:{count}"


def _as_whatsapp_message(message: Communication) -> TimelineWhatsappMessageRead | None:
    try:
        return TimelineWhatsappMessageRead.model_validate(message)
    except ValidationError:
        return None


def _group_whatsapp_by_thread_windows(
    whatsapp_messages: list[Communication],
    thread_windows: list[_EmailThreadWindow],
) -> list[list[Communication]]:
    if not thread_windows:
        return [whatsapp_messages] if whatsapp_messages else []

    buckets: list[list[Communication]] = [[] for _ in range(len(thread_windows) + 1)]
    anchors = [window.anchor_timestamp for window in thread_windows]

    for message in whatsapp_messages:
        created_at = _ensure_utc(message.created_at)
        index = 0
        while index < len(anchors) and created_at > anchors[index]:
            index += 1
        buckets[index].append(message)
    return buckets


def _build_whatsapp_groups(whatsapp_messages: list[Communication], thread_windows: list[_EmailThreadWindow]) -> list[TimelineWhatsappGroupRead]:
    buckets = _group_whatsapp_by_thread_windows(whatsapp_messages, thread_windows)
    groups: list[TimelineWhatsappGroupRead] = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        rendered_messages = [message for message in (_as_whatsapp_message(item) for item in bucket) if message is not None]
        if not rendered_messages:
            continue
        start_timestamp = _ensure_utc(bucket[0].created_at)
        end_timestamp = _ensure_utc(bucket[-1].created_at)
        group_label = "before_first_thread" if index == 0 else "after_last_thread" if index == len(thread_windows) else f"between_thread_{index}_and_{index + 1}"
        groups.append(
            TimelineWhatsappGroupRead(
                group_id=_build_whatsapp_group_id(group_label, start_timestamp, end_timestamp, len(rendered_messages)),
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                messages=rendered_messages,
                message_count=len(rendered_messages),
            )
        )
    return groups


def _build_whatsapp_blocks_for_thread(
    thread: Conversation,
    whatsapp_messages: list[Communication],
) -> list[TimelineWhatsappBlockRead]:
    messages = sorted(thread.messages or [], key=_thread_message_sort_key)
    if len(messages) < 2 or not whatsapp_messages:
        return []

    blocks: list[TimelineWhatsappBlockRead] = []
    whatsapp_index = 0
    for message_index in range(len(messages) - 1):
        left = _ensure_utc(messages[message_index].sent_at)
        right = _ensure_utc(messages[message_index + 1].sent_at)
        block_messages: list[TimelineWhatsappMessageRead] = []
        while whatsapp_index < len(whatsapp_messages):
            candidate = whatsapp_messages[whatsapp_index]
            candidate_at = _ensure_utc(candidate.created_at)
            if candidate_at <= left:
                whatsapp_index += 1
                continue
            if candidate_at > right:
                break
            rendered = _as_whatsapp_message(candidate)
            if rendered is not None:
                block_messages.append(rendered)
            whatsapp_index += 1
        if block_messages:
            blocks.append(
                TimelineWhatsappBlockRead(
                    block_id=_build_whatsapp_block_id(thread.id, message_index, left, right, len(block_messages)),
                    start_at=_ensure_utc(block_messages[0].created_at),
                    end_at=_ensure_utc(block_messages[-1].created_at),
                    messages=block_messages,
                    message_count=len(block_messages),
                )
            )
    return blocks


def build_tenant_thread_timeline(db: Session, tenant_id: int) -> MixedTimelineRead:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise ValueError("Tenant not found")

    conversations = _load_tenant_conversations(db, tenant_id)
    whatsapp_messages = _load_tenant_whatsapp(db, tenant_id)
    thread_windows = _build_thread_windows(conversations)

    whatsapp_blocks_by_thread_id: dict[int, list[TimelineWhatsappBlockRead]] = {}
    if whatsapp_messages:
        for index, window in enumerate(thread_windows):
            next_anchor = thread_windows[index + 1].anchor_timestamp if index + 1 < len(thread_windows) else None
            block_messages = [
                message
                for message in whatsapp_messages
                if _ensure_utc(message.created_at) > window.anchor_timestamp
                and (next_anchor is None or _ensure_utc(message.created_at) <= next_anchor)
            ]
            whatsapp_blocks_by_thread_id[window.thread.id] = _build_whatsapp_blocks_for_thread(window.thread, block_messages)

    items: list[TimelineEmailThreadRead | TimelineWhatsappGroupRead] = []
    whatsapp_groups = _build_whatsapp_groups(whatsapp_messages, thread_windows)

    thread_items: list[tuple[datetime, int, TimelineEmailThreadRead]] = []
    for window in thread_windows:
        messages = sorted(window.thread.messages or [], key=_thread_message_sort_key)
        thread_items.append(
            (
                window.anchor_timestamp,
                window.thread.id,
                TimelineEmailThreadRead(
                    thread_id=window.thread.id,
                    provider_thread_id=window.thread.provider_thread_id,
                    provider_account_id=window.thread.provider_account_id,
                    provider_account_email=getattr(window.thread, "provider_account_email", None),
                    provider_account_display_name=getattr(window.thread, "provider_account_display_name", None),
                    subject=window.thread.subject,
                    preview_text=window.thread.preview_text,
                    anchor_timestamp=window.anchor_timestamp,
                    messages=[TimelineMessageRead.model_validate({"id": message.id, "provider": message.provider, "provider_message_id": message.provider_message_id, "direction": message.direction, "sender_email": message.sender_email, "recipient_email": message.recipient_email, "subject": message.subject, "body": message.body, "body_text": (message.raw_payload or {}).get("body_text") if isinstance(message.raw_payload, dict) else None, "body_html": (message.raw_payload or {}).get("body_html") if isinstance(message.raw_payload, dict) else None, "sent_at": message.sent_at}) for message in messages],
                    whatsapp_blocks=whatsapp_blocks_by_thread_id.get(window.thread.id, []),
                ),
            )
        )

    combined: list[tuple[datetime, int, str, Any]] = []
    for anchor_timestamp, thread_id, thread_item in thread_items:
        combined.append((anchor_timestamp, thread_id, "email_thread", thread_item))
    for group in whatsapp_groups:
        start_timestamp = group.start_timestamp or datetime.min.replace(tzinfo=timezone.utc)
        combined.append((start_timestamp, -1, "whatsapp_group", group))

    combined.sort(key=lambda item: (item[0], item[1], 0 if item[2] == "email_thread" else 1), reverse=True)
    items = [item[3] for item in combined]

    return MixedTimelineRead(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        items=items,
    )
