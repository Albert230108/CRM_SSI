from __future__ import annotations

from datetime import datetime
import html
import os
import re
from typing import Any

import httpx

TOKEN_CACHE_DURATION = 3600
_token_cache: dict[str, dict[str, float | str]] = {}


def _refresh_token() -> str:
    token = os.getenv('BEDS24_REFRESH_TOKEN', '').strip()
    if not token:
        raise RuntimeError('BEDS24_REFRESH_TOKEN is not set')
    return token


async def _get_beds24_api_token(refresh_token: str) -> str:
    current_time = datetime.now().timestamp()
    cached = _token_cache.get(refresh_token)
    if cached and float(cached['expiry']) > current_time:
        return str(cached['token'])

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            'https://beds24.com/api/v2/authentication/token',
            headers={'refreshToken': refresh_token},
        )
    response.raise_for_status()
    token = response.json().get('token')
    if token:
        _token_cache[refresh_token] = {
            'token': str(token),
            'expiry': current_time + TOKEN_CACHE_DURATION,
        }
        return str(token)
    raise RuntimeError('Beds24 token exchange did not return a token')


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
        response = await client.get(
            'https://beds24.com/api/v2/bookings',
            params={'id': booking_id, 'includeInvoiceItems': 'true'},
        )
    response.raise_for_status()
    payload = response.json()
    data = payload.get('data') if isinstance(payload, dict) else payload
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {}
