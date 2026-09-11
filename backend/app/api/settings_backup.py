import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user, get_db
from app.services import settings_backup_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings-backup", tags=["settings-backup"])


def _snapshot_dir() -> Path:
    return Path(os.getenv("SETTINGS_BACKUP_SNAPSHOT_DIR", "/app/backups/settings"))


@router.get("/export", dependencies=[Depends(get_current_admin_user)])
def export_settings_backup(db: Session = Depends(get_db)) -> Response:
    payload = settings_backup_service.export_settings(db)
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    filename = f"crm-settings-backup-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/import", dependencies=[Depends(get_current_admin_user)])
async def import_settings_backup(
    mode: Literal["preview", "replace", "merge"] = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    raw = await file.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is not valid JSON.") from exc

    try:
        settings_backup_service.validate_backup_payload(payload)
    except settings_backup_service.SettingsBackupError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if mode == "preview":
        plan = settings_backup_service.preview_import(db, payload)
        return {"mode": "preview", "datasets": plan}

    try:
        snapshot_path = settings_backup_service.write_snapshot(db, _snapshot_dir())
    except OSError as exc:
        logger.exception("Failed to write pre-import settings snapshot")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not write a safety snapshot before import; nothing was changed.",
        ) from exc

    try:
        results = settings_backup_service.apply_import(db, payload, mode=mode)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Settings backup import failed; rolled back")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Import failed and was rolled back; no changes were applied.",
        ) from exc

    return {"mode": mode, "datasets": results, "snapshotPath": str(snapshot_path)}
