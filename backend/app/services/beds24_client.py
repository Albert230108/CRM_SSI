from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

READ_BASE_URL = "https://api.beds24.com/v2"
WRITE_BASE_URL = "https://beds24.com/api/v2"

_token_cache: dict[str, tuple[str, float]] = {}


def _refresh_token() -> str:
    token = os.getenv("BEDS24_REFRESH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BEDS24_REFRESH_TOKEN is not set")
    return token


def _extract_token_value(payload: Any) -> str | None:
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates += [payload.get("token"), payload.get("accessToken"), payload.get("apiToken")]
        for key in ("data", "result"):
            sub = payload.get(key)
            if isinstance(sub, dict):
                candidates += [sub.get("token"), sub.get("accessToken"), sub.get("apiToken")]
    elif isinstance(payload, list) and payload:
        return _extract_token_value(payload[0])
    for c in candidates:
        if c:
            return str(c).strip()
    return None


def _extract_ttl(payload: Any, default: int = 3600) -> int:
    if not isinstance(payload, dict):
        return default
    for key in ("expiresIn", "expiresInSeconds", "expires_in", "ttl"):
        v = payload.get(key)
        try:
            if v is not None:
                return max(60, int(float(v)))
        except (TypeError, ValueError):
            pass
    sub = payload.get("data")
    if isinstance(sub, dict):
        for key in ("expiresIn", "expiresInSeconds", "expires_in", "ttl"):
            v = sub.get(key)
            try:
                if v is not None:
                    return max(60, int(float(v)))
            except (TypeError, ValueError):
                pass
    return default


async def _get_access_token() -> str:
    refresh = _refresh_token()
    now = asyncio.get_event_loop().time()
    cached = _token_cache.get(refresh)
    if cached and cached[1] > now:
        return cached[0]

    url = f"{WRITE_BASE_URL}/authentication/token"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers={"accept": "application/json", "refreshToken": refresh})
        response.raise_for_status()
        payload = response.json()

    access_token = _extract_token_value(payload)
    if not access_token:
        raise RuntimeError(f"Beds24 token exchange did not return an access token: {payload}")

    ttl = _extract_ttl(payload)
    _token_cache[refresh] = (access_token, now + ttl - 30)
    return access_token


def _auth_headers() -> dict[str, str]:
    raise RuntimeError("Use _async_headers() inside an async context")


async def _async_headers() -> dict[str, str]:
    token = await _get_access_token()
    return {"Accept": "application/json", "token": token}


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None
) -> httpx.Response:
    max_retries = 5
    base_delay = 1.0
    for attempt in range(max_retries + 1):
        response = await client.get(url, params=params)
        if response.status_code == 429 and attempt < max_retries:
            try:
                delay = float(response.headers.get("Retry-After", 0) or 0)
            except (TypeError, ValueError):
                delay = 0.0
            delay = delay if delay > 0 else base_delay * (2 ** attempt)
            await asyncio.sleep(min(delay, 20.0))
            continue
        response.raise_for_status()
        return response
    response.raise_for_status()
    return response


async def get_bookings() -> list[dict[str, Any]]:
    headers = await _async_headers()
    params: dict[str, Any] = {"includeInfoItems": "true", "includeGuestDetails": "true"}
    all_items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        next_url: str | None = f"{READ_BASE_URL}/bookings"
        next_params: dict[str, Any] | None = params
        while next_url:
            response = await _get_with_retry(client, next_url, next_params)
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else payload
            if isinstance(data, list):
                all_items.extend(item for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                sub = data.get("bookings") or []
                all_items.extend(item for item in sub if isinstance(item, dict))
            pages = payload.get("pages", {}) if isinstance(payload, dict) else {}
            if isinstance(pages, dict) and pages.get("nextPageExists") and pages.get("nextPageLink"):
                next_url = str(pages["nextPageLink"])
                next_params = None
                await asyncio.sleep(0.2)
            else:
                next_url = None
    return all_items


async def get_booking_detail(booking_id: str) -> dict[str, Any]:
    headers = await _async_headers()
    params = {"includeInfoItems": "true", "includeGuestDetails": "true"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _get_with_retry(client, f"{READ_BASE_URL}/bookings/{booking_id}", params)
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {}


async def get_payments(booking_id: str) -> list[dict[str, Any]]:
    headers = await _async_headers()
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _get_with_retry(client, f"{READ_BASE_URL}/bookings/{booking_id}/payments")
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        data = data.get("payments") or []
    return [item for item in (data or []) if isinstance(item, dict)]


async def get_charges(booking_id: str) -> list[dict[str, Any]]:
    headers = await _async_headers()
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _get_with_retry(client, f"{READ_BASE_URL}/bookings/{booking_id}/charges")
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        data = data.get("charges") or []
    return [item for item in (data or []) if isinstance(item, dict)]
