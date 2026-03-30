from __future__ import annotations

import os
from threading import Lock
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx
import requests
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

router = APIRouter(prefix="/music", tags=["music"])
_command_lock = Lock()
_command_version = 0
_latest_command: dict[str, object] = {
    "version": 0,
    "action": "idle",
    "source_url": "",
    "stream_url": "",
}


class Esp32PlayUrlRequest(BaseModel):
    url: str


def _ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _safe_name(filename: str) -> str:
    return os.path.basename(filename)


def _list_mp3() -> list[str]:
    if not os.path.isdir(UPLOAD_DIR):
        return []
    return sorted([f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(".mp3")])


def _validate_remote_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http/https URLs are allowed")
    return url


@router.get("/list")
def list_music() -> dict[str, list[str]]:
    _ensure_upload_dir()
    return {"tracks": _list_mp3()}


@router.get("/health")
def music_health() -> dict[str, object]:
    _ensure_upload_dir()
    return {"status": "ok", "tracks": len(_list_mp3())}


@router.get("/esp32/command")
def get_esp32_command() -> dict[str, object]:
    with _command_lock:
        return dict(_latest_command)


@router.post("/esp32/play-url")
def set_esp32_play_url(payload: Esp32PlayUrlRequest) -> JSONResponse:
    global _command_version

    source_url = _validate_remote_url(payload.url.strip())
    stream_url = f"/music/stream?url={source_url}"
    with _command_lock:
        _command_version += 1
        _latest_command.update({
            "version": _command_version,
            "action": "play_url",
            "source_url": source_url,
            "stream_url": stream_url,
        })
        command = dict(_latest_command)

    return JSONResponse({"status": "ok", **command})


@router.post("/upload")
async def upload_music(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".mp3"):
        raise HTTPException(status_code=400, detail="Only .mp3 files are accepted")
    _ensure_upload_dir()
    safe_name = _safe_name(file.filename)
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    content = await file.read()
    with open(dest_path, "wb") as handle:
        handle.write(content)
    return JSONResponse({"status": "ok", "filename": safe_name, "bytes": len(content)})


@router.get("/stream")
def stream_url(url: str = Query(..., min_length=8)) -> StreamingResponse:
    _validate_remote_url(url)

    try:
        response = requests.get(url, stream=True, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Upstream fetch failed: {exc}") from exc

    def iterator() -> AsyncIterator[bytes]:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    content_type = response.headers.get("Content-Type", "audio/mpeg")
    headers = {"Accept-Ranges": response.headers.get("Accept-Ranges", "bytes")}
    return StreamingResponse(iterator(), media_type=content_type, headers=headers)


@router.get("/{filename:path}")
def serve_music(filename: str):
    _ensure_upload_dir()
    safe_name = _safe_name(filename)
    path = os.path.join(UPLOAD_DIR, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")

    def iterator() -> AsyncIterator[bytes]:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(8192)
                if not chunk:
                    break
                yield chunk

    headers = {"Accept-Ranges": "bytes"}
    return StreamingResponse(iterator(), media_type="audio/mpeg", headers=headers)
