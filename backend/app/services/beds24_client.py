import os
from typing import Any

import httpx

BASE_URL = "https://beds24.com/api/v2"
API_KEY = os.getenv("BEDS24_API_KEY")


def _headers() -> dict[str, str]:
    if not API_KEY:
        raise RuntimeError("BEDS24_API_KEY is not set")
    return {"X-Api-Key": API_KEY, "Accept": "application/json"}


async def _request(path: str, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(base_url=BASE_URL, headers=_headers(), timeout=30.0) as client:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()


async def get_bookings() -> Any:
    return await _request("/bookings")


async def get_booking_detail(booking_id: str) -> Any:
    return await _request(f"/bookings/{booking_id}")


async def get_payments(booking_id: str) -> Any:
    return await _request(f"/bookings/{booking_id}/payments")


async def get_charges(booking_id: str) -> Any:
    return await _request(f"/bookings/{booking_id}/charges")
