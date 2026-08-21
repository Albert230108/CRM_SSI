import logging
import time

from sqlalchemy.orm import Session

from app.models.communication import Communication
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.schemas.whatsapp_thread_link import WhatsAppChatResyncResult
from app.services.whatsapp_chat_directory import resync_whatsapp_chat
from app.services.whatsapp_client import WhatsAppBridgeError

logger = logging.getLogger(__name__)

# Shared between the live-inbound-message webhook trigger and the tenant-page-open trigger, so
# opening a tenant's page right after a message-triggered resync doesn't redundantly re-fire it.
AUTO_RESYNC_THROTTLE_SECONDS = 300

_last_resync_at: dict[int, float] = {}


def claim_auto_resync_slot(endpoint_id: int) -> bool:
    """Return True and mark the slot as used if this endpoint hasn't auto-resynced within the
    throttle window; return False (leaving the existing timestamp intact) otherwise.

    Marks the timestamp before the caller awaits the actual resync call, so a burst of
    near-simultaneous triggers (several inbound messages, or a message plus a page open) can't
    queue up multiple overlapping resyncs for the same chat.
    """
    now = time.monotonic()
    last = _last_resync_at.get(endpoint_id)
    if last is not None and now - last < AUTO_RESYNC_THROTTLE_SECONDS:
        return False
    _last_resync_at[endpoint_id] = now
    return True


async def resync_endpoint_and_reconcile(db: Session, tenant_id: int, link: TenantChannelEndpoint) -> WhatsAppChatResyncResult:
    """Force a full-history resync of one linked WhatsApp chat and reconcile existing messages'
    external_chat_namespace afterward, so they match the timeline filter.

    Mirrors resync_thread_whatsapp_link's resync+reconciliation logic in whatsapp_thread_links.py.
    """
    try:
        raw_result = await resync_whatsapp_chat(link.external_account_id, link.external_chat_namespace)
        resync_result = WhatsAppChatResyncResult(
            ok=bool(raw_result.get("ok", True)),
            fetched=int(raw_result.get("fetched") or 0),
            imported=int(raw_result.get("imported") or 0),
            deduped=int(raw_result.get("deduped") or 0),
            skipped_no_content=int(raw_result.get("skippedNoContent") or 0),
            failed=int(raw_result.get("failed") or 0),
        )
        logger.info(
            "whatsapp_auto_resync_completed tenant_id=%s link_id=%s result=%s",
            tenant_id,
            link.id,
            raw_result,
        )

        if resync_result.ok and link.external_account_id and link.external_chat_namespace:
            matching_messages = db.query(Communication).filter(
                Communication.tenant_id == tenant_id,
                Communication.channel == "whatsapp",
                Communication.external_account_id == link.external_account_id,
            ).all()

            chat_id_lower = link.external_chat_namespace.strip().lower()
            messages_updated = 0
            for msg in matching_messages:
                msg_identity = (msg.whatsapp_identity_key or msg.whatsapp_chat_id or "").strip().lower()
                if msg_identity and msg_identity == chat_id_lower:
                    if msg.external_chat_namespace != link.external_chat_namespace:
                        msg.external_chat_namespace = link.external_chat_namespace
                        messages_updated += 1

            if messages_updated > 0:
                db.commit()
                logger.info(
                    "whatsapp_auto_resync_reconciled_messages tenant_id=%s link_id=%s external_account_id=%s chat_id=%s count=%s",
                    tenant_id,
                    link.id,
                    link.external_account_id,
                    link.external_chat_namespace,
                    messages_updated,
                )
    except WhatsAppBridgeError as exc:
        resync_result = WhatsAppChatResyncResult(ok=False, error=exc.args[0] if exc.args else "Resync failed")
        logger.warning(
            "whatsapp_auto_resync_failed tenant_id=%s link_id=%s error=%s",
            tenant_id,
            link.id,
            exc,
        )

    return resync_result


def _active_linked_endpoints(db: Session, tenant_id: int) -> list[TenantChannelEndpoint]:
    return (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.tenant_id == tenant_id,
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.is_active.is_(True),
            TenantChannelEndpoint.unlinked_at.is_(None),
            TenantChannelEndpoint.external_chat_namespace.isnot(None),
        )
        .all()
    )


async def auto_resync_tenant_endpoints(db: Session, tenant_id: int) -> list[dict[str, object]]:
    """Resync every actively linked WhatsApp chat for a tenant, throttled per chat.

    Used by both the live-inbound-message webhook trigger (backend/app/webhooks/whatsapp.py)
    and the tenant-page-open trigger (POST .../whatsapp-links/resync-all in
    backend/app/api/whatsapp_thread_links.py). One chat's failure never blocks the others.
    """
    summary: list[dict[str, object]] = []
    for link in _active_linked_endpoints(db, tenant_id):
        if not claim_auto_resync_slot(link.id):
            summary.append({"endpoint_id": link.id, "status": "throttled"})
            continue
        result = await resync_endpoint_and_reconcile(db, tenant_id, link)
        summary.append({
            "endpoint_id": link.id,
            "status": "resynced" if result.ok else "error",
            "detail": result.error,
        })
    return summary
