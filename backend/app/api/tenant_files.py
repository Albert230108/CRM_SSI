"""Read-only local tenant-files tile for the CRM dashboard's "Files" card - the server-side
folder tab alongside the existing browser-connected local folder view (frontend/src/components/
OneDriveBox.tsx). Guarded by ordinary CRM user auth (get_current_user), unlike the Quotation
Manager's own tenant-files routes under app.api.quotation, which are reached through a scoped
quotation token instead - see that module's /quotation/tenant-files/* routes for the cross-tenant
search this same storage layer (app.services.tenant_files_storage) also backs.
"""

import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.services import tenant_files_storage

router = APIRouter(prefix="/tenant-files", tags=["tenant-files"])


def _entry_dict(entry: tenant_files_storage.FileEntry) -> dict:
    return {"name": entry.name, "kind": entry.kind, "size": entry.size, "relative_path": entry.relative_path}


@router.get("/tenant/{tenant_id}")
def list_tenant_files(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    result = tenant_files_storage.list_tenant_folder(
        booking_id=tenant.booking_id, first_name=tenant.first_name, last_name=tenant.last_name,
        check_in=tenant.check_in,
    )
    return {"folder_path": result["folder_path"], "items": [_entry_dict(item) for item in result["items"]]}


@router.post("/tenant/{tenant_id}/upload", status_code=status.HTTP_201_CREATED)
async def upload_tenant_file(
    tenant_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Drag-and-drop upload into a tenant's server-side folder (TENANT_FILES_ROOT). OneDrive stays
    the fallback store, so nothing is pushed there from here."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    entry = tenant_files_storage.save_tenant_file(
        booking_id=tenant.booking_id,
        first_name=tenant.first_name,
        last_name=tenant.last_name,
        check_in=tenant.check_in,
        filename=file.filename or "file",
        content=content,
    )
    return _entry_dict(entry)


@router.get("/download")
def download_tenant_file(
    path: str = Query(..., description="relative_path from list_tenant_files/search"),
    current_user: User = Depends(get_current_user),
) -> Response:
    resolved = tenant_files_storage.resolve_download_path(path)
    mime_type, _ = mimetypes.guess_type(resolved.name)
    return Response(
        content=resolved.read_bytes(),
        media_type=mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{resolved.name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
