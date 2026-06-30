from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.communication import Communication
from app.models.tenant import Tenant

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhooks"])


def _first_text(payload: dict[str, Any]) -> str:
    for key in ("message", "text", "body", "content"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _pick_sender(payload: dict[str, Any]) -> str | None:
    for key in ("from", "sender", "phone", "wa_id", "phone_number"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _pick_timestamp(payload: dict[str, Any]) -> datetime:
    value = payload.get("timestamp") or payload.get("created_at") or payload.get("date")
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)) or str(value).isdigit():
        raw = int(value)
        if raw > 10**12:
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _find_tenant(db: Session, sender: str | None, payload: dict[str, Any]) -> Tenant | None:
    candidates = []
    if sender:
        candidates.append(sender)
    for key in ("email", "customer_email", "tenant_email"):
        value = payload.get(key)
        if value:
            tenant = db.query(Tenant).filter(Tenant.email == str(value)).first()
            if tenant is not None:
                return tenant
    for candidate in candidates:
        tenant = db.query(Tenant).filter(Tenant.phone == candidate).first()
        if tenant is not None:
            return tenant
    return None


@router.post("")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")

    sender = _pick_sender(payload)
    tenant = _find_tenant(db, sender, payload)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    db.add(
        Communication(
            tenant_id=tenant.id,
            channel="whatsapp",
            subject=payload.get("subject"),
            message=_first_text(payload),
            created_at=_pick_timestamp(payload),
        )
    )
    db.commit()
    return {"status": "ok"}
