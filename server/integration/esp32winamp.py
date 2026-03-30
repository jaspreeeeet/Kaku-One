from __future__ import annotations

from typing import AsyncIterator
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from config import ESP32WINAMP_BASE_URL, ESP32WINAMP_TIMEOUT_S

router = APIRouter(prefix="/esp32winamp", tags=["esp32winamp"])


def _require_base_url() -> str:
    if not ESP32WINAMP_BASE_URL:
        raise HTTPException(
            status_code=503,
            detail="ESP32 Winamp integration is not configured. Set ESP32WINAMP_BASE_URL.",
        )
    return ESP32WINAMP_BASE_URL


async def _request(method: str, path: str) -> httpx.Response:
    url = f"{_require_base_url()}{path}"
    timeout = httpx.Timeout(ESP32WINAMP_TIMEOUT_S)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url)
            response.raise_for_status()
            return response
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ESP32 Winamp upstream error: {exc}") from exc


@router.get("/health")
async def health() -> JSONResponse:
    base_url = _require_base_url()
    try:
        response = await _request("GET", "/list")
        songs = [line for line in response.text.splitlines() if line.strip()]
        return JSONResponse({"status": "online", "base_url": base_url, "songs": len(songs)})
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"status": "offline", "base_url": base_url, "detail": exc.detail},
        )


@router.get("/list")
async def list_tracks() -> dict[str, list[str]]:
    response = await _request("GET", "/list")
    return {"tracks": [line.strip() for line in response.text.splitlines() if line.strip()]}


@router.get("/music/{filename:path}")
async def stream_track(filename: str) -> StreamingResponse:
    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=ESP32WINAMP_TIMEOUT_S))
    url = f"{_require_base_url()}/music/{quote(filename, safe='')}"

    try:
        request = client.build_request("GET", url)
        response = await client.send(request, stream=True)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        await client.aclose()
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"ESP32 Winamp upstream error: {exc}") from exc

    async def iterator() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    headers = {
        "Accept-Ranges": response.headers.get("Accept-Ranges", "bytes"),
        "Content-Length": response.headers.get("Content-Length", ""),
        "Cache-Control": "no-store",
    }
    return StreamingResponse(
        iterator(),
        media_type=response.headers.get("Content-Type", "audio/mpeg"),
        headers={key: value for key, value in headers.items() if value},
    )
