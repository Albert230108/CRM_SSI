from fastapi import FastAPI

from app.api.admin_invites import router as admin_invites_router
from app.api.auth import router as auth_router
from app.api.beds24_webhooks import router as beds24_webhook_router
from app.api.communications import router as communications_router
from app.api.invites import router as invites_router
from app.api.tenants import router as tenants_router
from app.api.users import router as users_router
from app.webhooks.whatsapp import router as whatsapp_webhook_router

app = FastAPI(title="CRM API")

app.include_router(auth_router, prefix="/api")
app.include_router(admin_invites_router, prefix="/api")
app.include_router(invites_router, prefix="/api")
app.include_router(communications_router, prefix="/api")
app.include_router(tenants_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(beds24_webhook_router, prefix="/api")
app.include_router(whatsapp_webhook_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}