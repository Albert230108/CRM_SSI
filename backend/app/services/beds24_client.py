from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status

READ_BASE_URL = "https://api.beds24.com/v2"
WRITE_BASE_URL = "https://beds24.com/api/v2"

# Custom info-item code used to tag emails linked to a tenant from the CRM, so the CRM and
# Beds24's booking info items stay reconcilable in both directions (mirrors the existing
# QM_CREATED_BY custom code convention already used for responsible_comm).
BEDS24_EMAIL_INFO_CODE = "CRM_EMAIL"

_token_cache: dict[str, tuple[str, float]] = {}
logger = logging.getLogger(__name__)


def _refresh_token() -> str:
    token = os.getenv("BEDS24_REFRESH_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="BEDS24_REFRESH_TOKEN is not set")
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

    url = f"{READ_BASE_URL}/authentication/token"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url, headers={"accept": "application/json", "refreshToken": refresh})
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            logger.warning("Beds24 token exchange timed out")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Beds24 token exchange timed out") from exc
        except httpx.HTTPStatusError as exc:
            upstream_status = exc.response.status_code if exc.response is not None else 502
            logger.warning("Beds24 token exchange failed upstream_status=%s", upstream_status)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 token exchange failed") from exc
        except httpx.HTTPError as exc:
            logger.warning("Beds24 token exchange network error: %s", type(exc).__name__)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Beds24 token exchange unavailable") from exc
        except ValueError as exc:
            logger.warning("Beds24 token exchange returned invalid JSON")
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 token exchange returned invalid JSON") from exc

    access_token = _extract_token_value(payload)
    if not access_token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 token exchange did not return an access token")

    ttl = _extract_ttl(payload)
    _token_cache[refresh] = (access_token, now + ttl - 30)
    return access_token


async def _async_headers() -> dict[str, str]:
    token = await _get_access_token()
    return {"Accept": "application/json", "token": token}


def _response_snippet(response: httpx.Response, limit: int = 240) -> str:
    try:
        text = response.text
    except Exception:
        return "<unreadable>"
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None
) -> httpx.Response:
    max_retries = 5
    base_delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            logger.warning("Beds24 request timed out url=%s", url)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Beds24 request timed out") from exc
        except httpx.HTTPError as exc:
            logger.warning("Beds24 request network error url=%s error=%s", url, type(exc).__name__)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Beds24 request unavailable") from exc

        if response.status_code == 429 and attempt < max_retries:
            try:
                delay = float(response.headers.get("Retry-After", 0) or 0)
            except (TypeError, ValueError):
                delay = 0.0
            delay = delay if delay > 0 else base_delay * (2 ** attempt)
            await asyncio.sleep(min(delay, 20.0))
            continue
        if response.status_code in (401, 403):
            logger.warning("Beds24 upstream auth failed url=%s status=%s body=%s", url, response.status_code, _response_snippet(response))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Beds24 credentials were rejected")
        if response.status_code >= 400:
            logger.warning("Beds24 upstream error url=%s status=%s body=%s", url, response.status_code, _response_snippet(response))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Beds24 upstream error ({response.status_code})")
        return response

    logger.warning("Beds24 upstream retry exhausted url=%s", url)
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Beds24 upstream retry exhausted")


async def _post_with_retry(
    client: httpx.AsyncClient, url: str, json_body: Any
) -> httpx.Response:
    max_retries = 5
    base_delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            response = await client.post(url, json=json_body)
        except httpx.TimeoutException as exc:
            logger.warning("Beds24 write request timed out url=%s", url)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Beds24 request timed out") from exc
        except httpx.HTTPError as exc:
            logger.warning("Beds24 write request network error url=%s error=%s", url, type(exc).__name__)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Beds24 request unavailable") from exc

        if response.status_code == 429 and attempt < max_retries:
            try:
                delay = float(response.headers.get("Retry-After", 0) or 0)
            except (TypeError, ValueError):
                delay = 0.0
            delay = delay if delay > 0 else base_delay * (2 ** attempt)
            await asyncio.sleep(min(delay, 20.0))
            continue
        if response.status_code in (401, 403):
            logger.warning("Beds24 upstream write auth failed url=%s status=%s body=%s", url, response.status_code, _response_snippet(response))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Beds24 credentials were rejected")
        if response.status_code >= 400:
            logger.warning("Beds24 upstream write error url=%s status=%s body=%s", url, response.status_code, _response_snippet(response))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Beds24 upstream error ({response.status_code})")
        return response

    logger.warning("Beds24 upstream write retry exhausted url=%s", url)
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Beds24 upstream retry exhausted")


def _extract_beds24_data(payload: Any, *, endpoint: str) -> Any:
    if isinstance(payload, dict):
        if payload.get("errors"):
            logger.warning("Beds24 %s returned errors=%s", endpoint, payload.get("errors"))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Beds24 {endpoint} returned an error response")
        if payload.get("error"):
            logger.warning("Beds24 %s returned error=%s", endpoint, payload.get("error"))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Beds24 {endpoint} returned an error response")
        if isinstance(payload.get("message"), str) and payload.get("message", "").strip() and "data" not in payload:
            logger.warning("Beds24 %s returned unexpected message=%s", endpoint, payload.get("message"))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Beds24 {endpoint} returned an unexpected response")
        return payload.get("data") if "data" in payload else payload
    return payload


def _booking_type_filters() -> list[str]:
    return ["confirmed", "requestWithManualConfirmation", "requestWithCreditCard"]


async def get_bookings() -> list[dict[str, Any]]:
    headers = await _async_headers()
    # Include current guests (checked out up to 1 month ago) through all future bookings.
    departure_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    params: dict[str, Any] = {
        "includeInfoItems": "true",
        "bookingType": _booking_type_filters(),
        "departureFrom": departure_from,
    }
    all_items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        next_url: str | None = f"{READ_BASE_URL}/bookings"
        next_params: dict[str, Any] | None = params
        while next_url:
            response = await _get_with_retry(client, next_url, next_params)
            try:
                payload = response.json()
            except ValueError as exc:
                logger.warning("Beds24 bookings response invalid JSON url=%s", next_url)
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 bookings response was not valid JSON") from exc
            data = _extract_beds24_data(payload, endpoint="bookings")
            if isinstance(data, list):
                all_items.extend(item for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                sub = data.get("bookings") or []
                all_items.extend(item for item in sub if isinstance(item, dict))
            else:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 bookings response shape was unexpected")
            pages = payload.get("pages", {}) if isinstance(payload, dict) else {}
            if isinstance(pages, dict) and pages.get("nextPageExists") and pages.get("nextPageLink"):
                next_url = str(pages["nextPageLink"])
                next_params = None
                await asyncio.sleep(0.2)
            else:
                next_url = None
    return all_items


async def get_booking_detail(booking_id: str) -> dict[str, Any]:
    # Beds24 v2 has no path-parameter form for a single booking: GET /bookings/{id} answers
    # 500 "Could not process request" for every id. The collection endpoint filtered by `id`
    # is the supported shape and returns a one-element list.
    headers = await _async_headers()
    params = {"id": booking_id, "includeInfoItems": "true"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _get_with_retry(client, f"{READ_BASE_URL}/bookings", params)
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Beds24 booking detail invalid JSON booking_id=%s", booking_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 booking detail response was not valid JSON") from exc
    data = _extract_beds24_data(payload, endpoint="booking detail")
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 booking response shape was unexpected")
    # An unrecognised filter name is silently ignored by Beds24 and answers 200 with the whole
    # unfiltered booking list, so confirm we got the booking we asked for rather than someone
    # else's data.
    returned_id = str(data.get("id") or "").strip()
    if returned_id and returned_id != str(booking_id).strip():
        logger.warning("Beds24 booking detail id mismatch requested=%s returned=%s", booking_id, returned_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 returned a different booking than requested")
    return data


async def get_payments(booking_id: str) -> list[dict[str, Any]]:
    headers = await _async_headers()
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _get_with_retry(client, f"{READ_BASE_URL}/bookings/{booking_id}/invoiceitems")
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Beds24 payments invalid JSON booking_id=%s", booking_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 payments response was not valid JSON") from exc
    data = _extract_beds24_data(payload, endpoint="payments")
    if isinstance(data, dict):
        data = data.get("invoiceItems") or data.get("items") or []
    items = [item for item in (data or []) if isinstance(item, dict)]
    return [item for item in items if str(item.get("type", "")).lower() in ("payment", "pay", "deposit")]


async def get_charges(booking_id: str) -> list[dict[str, Any]]:
    headers = await _async_headers()
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _get_with_retry(client, f"{READ_BASE_URL}/bookings/{booking_id}/invoiceitems")
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Beds24 charges invalid JSON booking_id=%s", booking_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 charges response was not valid JSON") from exc
    data = _extract_beds24_data(payload, endpoint="charges")
    if isinstance(data, dict):
        data = data.get("invoiceItems") or data.get("items") or []
    items = [item for item in (data or []) if isinstance(item, dict)]
    return [item for item in items if str(item.get("type", "")).lower() not in ("payment", "pay", "deposit")]


async def update_booking_notes(booking_id: str, notes: str | None) -> None:
    headers = await _async_headers()
    body = [{"id": booking_id, "notes": notes or ""}]
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _post_with_retry(client, f"{WRITE_BASE_URL}/bookings", body)
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Beds24 update notes invalid JSON booking_id=%s", booking_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 update notes response was not valid JSON") from exc
    _extract_beds24_data(payload, endpoint="update booking notes")


async def get_booking_info_items(booking_id: str) -> list[dict[str, Any]]:
    headers = await _async_headers()
    params: dict[str, Any] = {"id": booking_id, "includeInfoItems": "true"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _get_with_retry(client, f"{READ_BASE_URL}/bookings", params)
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Beds24 booking info items invalid JSON booking_id=%s", booking_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 booking info items response was not valid JSON") from exc
    data = _extract_beds24_data(payload, endpoint="booking info items")
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return []
    info_items = data.get("infoItems")
    return [item for item in info_items if isinstance(item, dict)] if isinstance(info_items, list) else []


async def add_booking_info_item(booking_id: str, code: str, text: str) -> dict | None:
    headers = await _async_headers()
    body = [{"id": booking_id, "infoItems": [{"code": code, "text": text}]}]
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _post_with_retry(client, f"{WRITE_BASE_URL}/bookings", body)
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Beds24 add info item invalid JSON booking_id=%s", booking_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 add info item response was not valid JSON") from exc
    data = _extract_beds24_data(payload, endpoint="add booking info item")
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        info_items = data.get("infoItems")
        if isinstance(info_items, list):
            for item in info_items:
                if isinstance(item, dict) and item.get("code") == code and item.get("text") == text:
                    return item

    # The write response doesn't always echo back the booking's infoItems (observed in
    # production: the POST succeeds and the item shows up in Beds24, but the response body
    # we get back has no infoItems to read the new id from) -- fall back to reading the
    # booking back so we still capture the id needed to delete this item later.
    logger.info(
        "Beds24 add info item response had no matching infoItems entry, falling back to re-fetch booking_id=%s code=%s",
        booking_id,
        code,
    )
    for item in await get_booking_info_items(booking_id):
        if item.get("code") == code and item.get("text") == text:
            return item
    logger.warning("Beds24 add info item could not confirm the new item after re-fetch booking_id=%s code=%s", booking_id, code)
    return None


async def delete_booking_info_item(booking_id: str, info_item_id: str) -> None:
    headers = await _async_headers()
    body = [{"id": booking_id, "infoItems": [{"id": info_item_id}]}]
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        response = await _post_with_retry(client, f"{WRITE_BASE_URL}/bookings", body)
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Beds24 delete info item invalid JSON booking_id=%s", booking_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 delete info item response was not valid JSON") from exc
    _extract_beds24_data(payload, endpoint="delete booking info item")
