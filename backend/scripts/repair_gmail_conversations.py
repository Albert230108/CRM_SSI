from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant

PROVIDER_GMAIL = "gmail"


def _email_address(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    raw_value = raw_value.strip().lower()
    if "<" in raw_value and ">" in raw_value:
        start = raw_value.rfind("<")
        end = raw_value.rfind(">")
        if start >= 0 and end > start:
            raw_value = raw_value[start + 1 : end].strip().lower()
    return raw_value or None


def _thread_payload_messages(conversation: Conversation, db) -> list[dict[str, Any]]:
    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation.id)
        .filter(ConversationMessage.provider == PROVIDER_GMAIL)
        .order_by(ConversationMessage.sent_at.asc(), ConversationMessage.id.asc())
        .all()
    )
    payloads: list[dict[str, Any]] = []
    for message in messages:
        raw_payload = message.raw_payload or {}
        gmail_payload = raw_payload.get("gmail") if isinstance(raw_payload, dict) else None
        if isinstance(gmail_payload, dict):
            payloads.append(gmail_payload)
    return payloads


def _thread_message_ids(payloads: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for payload in payloads:
        message_id = str(payload.get("id") or "").strip()
        if message_id:
            ids.append(message_id)
    return ids


def _thread_id_from_payloads(payloads: list[dict[str, Any]]) -> str | None:
    for payload in payloads:
        thread_id = str(payload.get("threadId") or "").strip()
        if thread_id:
            return thread_id
    return None


def _account_id_from_payloads(payloads: list[dict[str, Any]], accounts: list[GmailAccount]) -> int | None:
    account_lookup = {account.email_address.strip().lower(): account.id for account in accounts if account.email_address}
    counts: Counter[int] = Counter()
    for payload in payloads:
        header_map = {}
        for header in (payload.get("payload") or {}).get("headers") or []:
            name = str(header.get("name") or "").lower()
            value = str(header.get("value") or "").strip()
            if name:
                header_map[name] = value
        for field in ("from", "to", "cc", "bcc"):
            raw_value = header_map.get(field)
            if not raw_value:
                continue
            for candidate in raw_value.split(","):
                address = _email_address(candidate)
                if address and address in account_lookup:
                    counts[account_lookup[address]] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _tenant_email_candidate(payloads: list[dict[str, Any]], account_email: str | None) -> str | None:
    seen: set[str] = set()
    candidates: list[str] = []
    account_email = (account_email or "").strip().lower()
    for payload in payloads:
        header_map = {}
        for header in (payload.get("payload") or {}).get("headers") or []:
            name = str(header.get("name") or "").lower()
            value = str(header.get("value") or "").strip()
            if name:
                header_map[name] = value
        for field in ("from", "to", "cc", "bcc"):
            raw_value = header_map.get(field)
            if not raw_value:
                continue
            for candidate in raw_value.split(","):
                address = _email_address(candidate)
                if address and address != account_email and address not in seen:
                    seen.add(address)
                    candidates.append(address)
    return candidates[0] if len(candidates) == 1 else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair Gmail conversations missing thread/account metadata")
    parser.add_argument("--apply", action="store_true", help="Persist repairs instead of dry-running")
    parser.add_argument("--tenant-id", type=int, default=None, help="Limit repair to a single tenant id")
    parser.add_argument("--conversation-id", type=int, default=None, help="Limit repair to a single conversation id")
    parser.add_argument("--limit", type=int, default=None, help="Limit scanned conversations")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Conversation).filter(Conversation.provider == PROVIDER_GMAIL)
        if args.tenant_id is not None:
            query = query.filter(Conversation.tenant_id == args.tenant_id)
        if args.conversation_id is not None:
            query = query.filter(Conversation.id == args.conversation_id)
        query = query.order_by(Conversation.id.asc())
        if args.limit is not None:
            query = query.limit(args.limit)

        accounts = db.query(GmailAccount).filter(GmailAccount.is_active.is_(True)).all()
        results: list[dict[str, Any]] = []

        for conversation in query.all():
            payloads = _thread_payload_messages(conversation, db)
            provider_account_id_before = conversation.provider_account_id
            provider_thread_id_before = conversation.provider_thread_id
            thread_id = provider_thread_id_before or _thread_id_from_payloads(payloads)
            account_id = provider_account_id_before or _account_id_from_payloads(payloads, accounts)
            tenant = db.query(Tenant).filter(Tenant.id == conversation.tenant_id).first() if conversation.tenant_id is not None else None
            account = next((item for item in accounts if item.id == account_id), None)
            tenant_email = _tenant_email_candidate(payloads, account.email_address if account else None)

            changes: dict[str, Any] = {}
            if thread_id and not provider_thread_id_before:
                changes["provider_thread_id"] = thread_id
            if account_id and provider_account_id_before is None:
                changes["provider_account_id"] = account_id
            if tenant is not None and not tenant.email and tenant_email:
                changes["tenant_email"] = tenant_email

            if args.apply:
                if "provider_thread_id" in changes:
                    conversation.provider_thread_id = changes["provider_thread_id"]
                if "provider_account_id" in changes:
                    conversation.provider_account_id = changes["provider_account_id"]
                if "tenant_email" in changes and tenant is not None:
                    tenant.email = changes["tenant_email"]
                if changes:
                    db.flush()

            results.append(
                {
                    "conversation_id": conversation.id,
                    "tenant_id": conversation.tenant_id,
                    "provider_account_id_before": provider_account_id_before,
                    "provider_thread_id_before": provider_thread_id_before,
                    "thread_id_candidate": thread_id,
                    "account_id_candidate": account_id,
                    "tenant_email_candidate": tenant_email,
                    "changes": changes,
                }
            )

        if args.apply:
            db.commit()
        print(json.dumps({"apply": args.apply, "count": len(results), "results": results}, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
