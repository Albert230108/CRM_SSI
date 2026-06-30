from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.communications import router as communications_router
from app.api.tenants import router as tenants_router
from app.webhooks.whatsapp import router as whatsapp_webhook_router
from app.webhooks.beds24 import router as beds24_webhook_router
from app.api.users import router as users_router

app = FastAPI(title="CRM API")

app.include_router(auth_router)
app.include_router(communications_router)
app.include_router(tenants_router)
app.include_router(users_router)
app.include_router(beds24_webhook_router)
app.include_router(whatsapp_webhook_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
