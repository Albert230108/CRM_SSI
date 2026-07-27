from __future__ import annotations

from datetime import datetime
import html
import logging
import os
import re
from typing import Any

import httpx
from fastapi import HTTPException, status

TOKEN_CACHE_DURATION = 3600
_token_cache: dict[str, dict[str, float | str]] = {}
logger = logging.getLogger(__name__)


def _response_snippet(response: httpx.Response, limit: int = 240) -> str:
    try:
        text = response.text
    except Exception:
        return '<unreadable>'
    text = ' '.join(text.split())
    return text[:limit] + ('...' if len(text) > limit else '')


def _refresh_token() -> str:
    token = os.getenv('BEDS24_REFRESH_TOKEN', '').strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='BEDS24_REFRESH_TOKEN is not set')
    return token


async def _get_beds24_api_token(refresh_token: str) -> str:
    current_time = datetime.now().timestamp()
    cached = _token_cache.get(refresh_token)
    if cached and float(cached['expiry']) > current_time:
        return str(cached['token'])

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(
                'https://beds24.com/api/v2/authentication/token',
                headers={'refreshToken': refresh_token},
            )
            response.raise_for_status()
            token_payload = response.json()
        except httpx.TimeoutException as exc:
            logger.warning('Beds24 token exchange timed out')
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Beds24 token exchange timed out') from exc
        except httpx.HTTPStatusError as exc:
            upstream_status = exc.response.status_code if exc.response is not None else 502
            logger.warning('Beds24 token exchange failed upstream_status=%s body=%s', upstream_status, _response_snippet(exc.response) if exc.response is not None else '<no response>')
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Beds24 token exchange failed') from exc
        except httpx.HTTPError as exc:
            logger.warning('Beds24 token exchange network error: %s', type(exc).__name__)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Beds24 token exchange unavailable') from exc
        except ValueError as exc:
            logger.warning('Beds24 token exchange returned invalid JSON')
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Beds24 token exchange returned invalid JSON') from exc
    token = token_payload.get('token')
    if token:
        _token_cache[refresh_token] = {
            'token': str(token),
            'expiry': current_time + TOKEN_CACHE_DURATION,
        }
        return str(token)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Beds24 token exchange did not return a token')


async def _auth_headers() -> dict[str, str]:
    token = await _get_beds24_api_token(_refresh_token())
    return {'accept': 'application/json', 'token': token, 'Content-Type': 'application/json'}


def _strip_description(value: Any) -> str:
    text = html.unescape(str(value or ''))
    text = re.sub(r'<a\b[^>]*>(.*?)</a>', r'\1', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'##NOLINK##', '', text, flags=re.IGNORECASE)
    return re.sub(r'<[^>]+>', '', text).strip()


async def fetch_booking_with_invoice(booking_id: str) -> dict[str, Any]:
    headers = await _auth_headers()
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        try:
            response = await client.get(
                'https://beds24.com/api/v2/bookings',
                params={'id': booking_id, 'includeInvoiceItems': 'true'},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            logger.warning('Beds24 booking fetch timed out booking_id=%s endpoint=%s', booking_id, 'https://beds24.com/api/v2/bookings')
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Beds24 booking fetch timed out') from exc
        except httpx.HTTPStatusError as exc:
            upstream_status = exc.response.status_code if exc.response is not None else 502
            logger.warning('Beds24 booking fetch failed booking_id=%s endpoint=%s upstream_status=%s body=%s', booking_id, 'https://beds24.com/api/v2/bookings', upstream_status, _response_snippet(exc.response) if exc.response is not None else '<no response>')
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f'Beds24 booking fetch failed ({upstream_status})') from exc
        except httpx.HTTPError as exc:
            logger.warning('Beds24 booking fetch network error booking_id=%s endpoint=%s error=%s', booking_id, 'https://beds24.com/api/v2/bookings', type(exc).__name__)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Beds24 booking fetch unavailable') from exc
        except ValueError as exc:
            logger.warning('Beds24 booking fetch returned invalid JSON booking_id=%s endpoint=%s', booking_id, 'https://beds24.com/api/v2/bookings')
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Beds24 booking fetch returned invalid JSON') from exc
    data = payload.get('data') if isinstance(payload, dict) else payload
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Beds24 booking response shape was unexpected')
    return data


async def _post_booking_update(client: httpx.AsyncClient, booking_id: str, payload: dict[str, Any], step: str) -> None:
    try:
        response = await client.post('https://beds24.com/api/v2/bookings', json=[payload])
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException as exc:
        logger.warning('Beds24 booking update timed out booking_id=%s step=%s', booking_id, step)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f'Beds24 booking update timed out ({step})') from exc
    except httpx.HTTPStatusError as exc:
        upstream_status = exc.response.status_code if exc.response is not None else 502
        logger.warning('Beds24 booking update failed booking_id=%s step=%s upstream_status=%s body=%s', booking_id, step, upstream_status, _response_snippet(exc.response) if exc.response is not None else '<no response>')
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f'Beds24 booking update failed ({step}, upstream status {upstream_status})') from exc
    except httpx.HTTPError as exc:
        logger.warning('Beds24 booking update network error booking_id=%s step=%s error=%s', booking_id, step, type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f'Beds24 booking update unavailable ({step})') from exc
    except ValueError as exc:
        logger.warning('Beds24 booking update returned invalid JSON booking_id=%s step=%s', booking_id, step)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f'Beds24 booking update returned invalid JSON ({step})') from exc

    if not (isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get('success')):
        error_detail = _response_snippet(response)
        logger.warning('Beds24 booking update rejected booking_id=%s step=%s response=%s', booking_id, step, error_detail)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f'Beds24 rejected the booking update ({step}): {error_detail}')


async def update_booking_invoice_items(
    booking_id: str,
    original_invoice_item_ids: list[str],
    final_invoice_items: list[dict[str, Any]],
) -> None:
    """
    Replace all invoice items on a Beds24 booking with a new set, via the same
    two-step delete-then-recreate flow the desktop Quotation Manager already
    uses (interface.py's send_booking_update_to_api): Beds24's API has no
    single "replace invoice items" call, so existing items are deleted by id
    first, then the full new set is submitted as a second update.

    Raises HTTPException if either step is rejected by Beds24 - callers
    should treat this as a hard failure rather than partially syncing.
    """
    headers = await _auth_headers()
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        if original_invoice_item_ids:
            delete_payload = {
                'id': booking_id,
                'invoiceItems': [{'id': item_id} for item_id in original_invoice_item_ids],
            }
            await _post_booking_update(client, booking_id, delete_payload, step='delete_invoice_items')

        final_payload = {'id': booking_id, 'invoiceItems': final_invoice_items}
        await _post_booking_update(client, booking_id, final_payload, step='update_booking')
