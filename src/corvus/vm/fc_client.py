"""Firecracker HTTP API client."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx


class FirecrackerClient:
    def __init__(self, api_socket: Path) -> None:
        self.api_socket = api_socket
        self._transport = httpx.AsyncHTTPTransport(uds=str(api_socket))
        self._client = httpx.AsyncClient(
            transport=self._transport,
            base_url="http://localhost",
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def put(self, path: str, body: dict[str, Any]) -> None:
        resp = await self._client.put(path, json=body)
        self._raise_for_status(path, resp)

    async def patch(self, path: str, body: dict[str, Any]) -> None:
        resp = await self._client.patch(path, json=body)
        self._raise_for_status(path, resp)

    async def get(self, path: str) -> dict[str, Any]:
        resp = await self._client.get(path)
        self._raise_for_status(path, resp)
        return resp.json()

    @staticmethod
    def _raise_for_status(path: str, resp: httpx.Response) -> None:
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = resp.text.strip()
            if detail:
                raise RuntimeError(
                    f"Firecracker API {path} failed with {resp.status_code}: {detail}"
                ) from exc
            raise


async def wait_for_api_socket(path: Path, timeout: float = 10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if path.exists():
            return True
        await asyncio.sleep(0.05)
    return False
