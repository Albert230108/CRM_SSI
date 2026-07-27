from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.gmail_integration import ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant_email_address import TenantEmailAddress
from app.api.tenant_email_links import _remove_conversations_for_matched_email

# _upsert_thread previously always recorded matched_email as the tenant's primary email, even
# when a message actually matched via a secondary linked address. This meant unlinking a
# secondary email could never find (and delete) the conversations it should have removed. This
# script recomputes matched_email from each conversation's actual message headers, then re-runs
# deletion for links that were already manually unlinked but whose conversations were never
# removed because of the wrong value.


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


def _candidate_addresses(db, tenant: Tenant) -> list[str]:
    addresses: list[str] = []
    if tenant.email:
        addresses.append(tenant.email.strip().lower())
    linked = db.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant.id).order_by(TenantEmailAddress.created_at.asc()).all()
    for row in linked:
        email = (row.email or "").strip().lower()
        if email and email not in addresses:
            addresses.append(email)
    return addresses


def _addresses_in_message(message: ConversationMessage) -> set[str]:
    addresses: set[str] = set()
    raw = message.raw_payload or {}
    gmail_message = raw.get("gmail") if isinstance(raw, dict) else None
    if isinstance(gmail_message, dict):
        header_map: dict[str, str] = {}
        for header in (gmail_message.get("payload") or {}).get("headers") or []:
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
                if address:
                    addresses.add(address)
    if message.sender_email:
        addresses.add(message.sender_email.strip().lower())
    if message.recipient_email:
        addresses.add(message.recipient_email.strip().lower())
    return addresses


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair TenantConversationLink.matched_email and remove conversations orphaned by the bug")
    parser.add_argument("--apply", action="store_true", help="Persist repairs instead of dry-running")
    parser.add_argument("--tenant-id", type=int, default=None, help="Limit repair to a single tenant id")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        link_query = db.query(TenantConversationLink).filter(
            TenantConversationLink.unlinked_at.is_(None),
            TenantConversationLink.source == "email_match",
        )
        if args.tenant_id is not None:
            link_query = link_query.filter(TenantConversationLink.tenant_id == args.tenant_id)
        links = link_query.all()

        matched_email_fixes: list[dict[str, Any]] = []
        for link in links:
            tenant = db.query(Tenant).filter(Tenant.id == link.tenant_id).first()
            if tenant is None:
                continue
            candidates = _candidate_addresses(db, tenant)
            if not candidates:
                continue

            messages = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == link.conversation_id).all()
            message_addresses: set[str] = set()
            for message in messages:
                message_addresses |= _addresses_in_message(message)

            correct_address = next((addr for addr in candidates if addr in message_addresses), None)
            if correct_address and link.matched_email != correct_address:
                matched_email_fixes.append(
                    {
                        "tenant_id": link.tenant_id,
                        "conversation_id": link.conversation_id,
                        "before": link.matched_email,
                        "after": correct_address,
                    }
                )
                link.matched_email = correct_address

        # This session is autoflush=False, so Step 2's queries wouldn't otherwise see the
        # matched_email corrections just made above (in the same uncommitted transaction).
        db.flush()

        email_query = db.query(TenantEmailAddress).filter(
            TenantEmailAddress.is_active.is_(False),
            TenantEmailAddress.unlinked_by_user_id.isnot(None),
        )
        if args.tenant_id is not None:
            email_query = email_query.filter(TenantEmailAddress.tenant_id == args.tenant_id)
        stale_unlinks = email_query.all()

        orphan_cleanup: list[dict[str, Any]] = []
        for unlinked in stale_unlinks:
            deleted, shared_unlinked = _remove_conversations_for_matched_email(db, unlinked.tenant_id, unlinked.email)
            if deleted or shared_unlinked:
                orphan_cleanup.append(
                    {
                        "tenant_id": unlinked.tenant_id,
                        "email": unlinked.email,
                        "conversations_deleted": deleted,
                        "conversations_unlinked_from_shared": shared_unlinked,
                    }
                )

        if args.apply:
            db.commit()
        else:
            db.rollback()

        print(
            json.dumps(
                {
                    "apply": args.apply,
                    "matched_email_fixes": matched_email_fixes,
                    "orphan_cleanup": orphan_cleanup,
                },
                indent=2,
                default=str,
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
