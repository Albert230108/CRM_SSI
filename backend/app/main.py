import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin_invites import router as admin_invites_router
from app.api.admin_sync import router as admin_sync_router
from app.api.auth import router as auth_router
from app.api.beds24_webhooks import router as beds24_webhook_router
from app.api.communications import router as communications_router
from app.api.gmail_integration import _sync_gmail_account
from app.api.gmail_integration import router as gmail_integration_router
from app.api.invites import router as invites_router
from app.api.tenants import router as tenants_router
from app.api.tenant_channel_endpoints import router as tenant_channel_endpoints_router
from app.api.users import router as users_router
from app.api.whatsapp_thread_links import router as whatsapp_thread_links_router
from app.database import SessionLocal
from app.models.gmail_integration import GmailAccount
from app.webhooks.whatsapp import router as whatsapp_webhook_router

logger = logging.getLogger(__name__)

EMAIL_POLL_INTERVAL_SECONDS = int(os.getenv("EMAIL_POLL_INTERVAL_SECONDS", "45"))


async def _poll_gmail_accounts_forever() -> None:
    while True:
        await asyncio.sleep(EMAIL_POLL_INTERVAL_SECONDS)
        db = SessionLocal()
        try:
            accounts = db.query(GmailAccount).filter(GmailAccount.is_active.is_(True)).order_by(GmailAccount.id.asc()).all()
            for account in accounts:
                try:
                    _sync_gmail_account(db, account)
                except Exception:
                    logger.exception("Background Gmail sync failed account_id=%s", account.id)
        except Exception:
            logger.exception("Background Gmail sync loop failed to load accounts")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_poll_gmail_accounts_forever())
    logger.info("Started background Gmail poll loop interval_seconds=%s", EMAIL_POLL_INTERVAL_SECONDS)
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="CRM API", redirect_slashes=False, lifespan=lifespan)

resolved_whatsapp_service_url = os.getenv("WHATSAPP_SERVICE_URL", "").strip() or "<unset>"
print(f"[backend] WHATSAPP_SERVICE_URL={resolved_whatsapp_service_url}")

app.include_router(auth_router, prefix="/api")
app.include_router(admin_invites_router, prefix="/api")
app.include_router(admin_sync_router, prefix="/api")
app.include_router(invites_router, prefix="/api")
app.include_router(communications_router, prefix="/api")
app.include_router(gmail_integration_router)
app.include_router(tenants_router, prefix="/api")
app.include_router(tenant_channel_endpoints_router, prefix="/api")
app.include_router(whatsapp_thread_links_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(beds24_webhook_router, prefix="/api")
app.include_router(whatsapp_webhook_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
