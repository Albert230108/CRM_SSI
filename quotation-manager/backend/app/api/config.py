from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.core.quotation_token import verify_quotation_token
from app.services import config_store

router = APIRouter(prefix="/config", tags=["config"])

# The editable config files, exposed read/write to the Price/Discount/Admin editors.
ALLOWED = {"admin-costs", "base-prices", "prices", "discount-rules"}


@router.get("/{name}")
def get_config(name: str, _token=Depends(verify_quotation_token)) -> dict:
    if name not in ALLOWED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown config '{name}'")
    try:
        return config_store.get_config(name)
    except config_store.ConfigStoreError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{name}")
def save_config(name: str, body: Any = Body(...), _token=Depends(verify_quotation_token)) -> dict:
    if name not in ALLOWED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown config '{name}'")
    try:
        return config_store.save_config(name, body)
    except config_store.ConfigStoreError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
