import os
from typing import Any
import httpx

_BASE_URL = os.getenv("PIPEDRIVE_BASE_URL", "https://api.pipedrive.com/v1")


async def pd(method: str, path: str, data: dict | None = None, params: dict | None = None) -> Any:
    """Authenticated Pipedrive API call. Returns response['data'] or raises on error."""
    merged = {**(params or {}), "api_token": os.environ["PIPEDRIVE_API_TOKEN"]}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method=method.upper(),
            url=f"{_BASE_URL.rstrip('/')}/{path.lstrip('/')}",
            params=merged,
            json=data,
        )
        response.raise_for_status()
        body = response.json()
    if not body.get("success"):
        raise ValueError(body.get("error", "Pipedrive API error"))
    return body.get("data")


async def pd_raw(method: str, path: str, data: dict | None = None, params: dict | None = None) -> Any:
    """
    Like pd() but returns the full response envelope including additional_data.
    Use when you need pagination cursors or other metadata that pd() discards.
    """
    merged = {**(params or {}), "api_token": os.environ["PIPEDRIVE_API_TOKEN"]}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method=method.upper(),
            url=f"{_BASE_URL.rstrip('/')}/{path.lstrip('/')}",
            params=merged,
            json=data,
        )
        response.raise_for_status()
        body = response.json()
    if not body.get("success"):
        raise ValueError(body.get("error", "Pipedrive API error"))
    return body
