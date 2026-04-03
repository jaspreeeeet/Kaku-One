from __future__ import annotations

import logging
import os
from threading import Lock
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx
import requests
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from music import blob_store
from ws_manager import notify_sync

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
if os.environ.get("VERCEL"):
    UPLOAD_DIR = "/tmp/uploads"
else:
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

# Use Vercel Blob when the token is configured (serverless-safe persistent storage)
USE_BLOB = blob_store.is_available()

router = APIRouter(prefix="/music", tags=["music"])
_command_lock = Lock()
_command_version = 0
_latest_command: dict[str, object] = {
    "version": 0,
    "action": "idle",
    "file": "",
    "source_url": "",
    "stream_url": "",
}
_state_lock = Lock()
_latest_state: dict[str, object] = {
    "state": "stopped",
    "file": "",
    "source": "",
    "device_ip": "",
    "updated_at_version": 0,
}


class Esp32PlayUrlRequest(BaseModel):
    url: str


class Esp32CommandRequest(BaseModel):
    action: str
    file: str = ""

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"play", "pause", "stop"}:
            raise ValueError("Action must be play, pause, or stop")
        return normalized

    @field_validator("file")
    @classmethod
    def validate_file(cls, value: str) -> str:
        return _safe_name(value.strip())


class Esp32StateUpdateRequest(BaseModel):
    state: str
    file: str = ""
    source: str = ""
    device_ip: str = ""

    @field_validator("state")
    @classmethod
    def validate_state(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"stopped", "playing", "paused"}:
            raise ValueError("State must be stopped, playing, or paused")
        return normalized

    @field_validator("file")
    @classmethod
    def validate_state_file(cls, value: str) -> str:
        return _safe_name(value.strip())

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"", "local", "remote"}:
            raise ValueError("Source must be local, remote, or empty")
        return normalized

    @field_validator("device_ip")
    @classmethod
    def validate_device_ip(cls, value: str) -> str:
        return value.strip()


def _set_command(
    action: str,
    *,
    file: str = "",
    source_url: str = "",
    stream_url: str = "",
) -> dict[str, object]:
    global _command_version

    with _command_lock:
        _command_version += 1
        _latest_command.update({
            "version": _command_version,
            "action": action,
            "file": file,
            "source_url": source_url,
            "stream_url": stream_url,
        })
        return dict(_latest_command)


def _update_state(
    *,
    state: str,
    file: str = "",
    source: str = "",
    device_ip: str = "",
    version: int | None = None,
) -> dict[str, object]:
    with _state_lock:
        _latest_state.update({
            "state": state,
            "file": file,
            "source": source,
            "device_ip": device_ip,
            "updated_at_version": version if version is not None else _latest_state["updated_at_version"],
        })
        return dict(_latest_state)


def _ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _safe_name(filename: str) -> str:
    return os.path.basename(filename)


def _list_mp3() -> list[str]:
    if USE_BLOB:
        return blob_store.list_mp3_names()
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


@router.post("/esp32/command")
def set_esp32_command(payload: Esp32CommandRequest) -> JSONResponse:
    if payload.action == "play" and not payload.file:
        raise HTTPException(status_code=400, detail="File is required for play action")
    command = _set_command(payload.action, file=payload.file)
    notify_sync({"type": "command", **command}, target="esp32")
    return JSONResponse({"status": "ok", **command})


@router.post("/esp32/play-url")
def set_esp32_play_url(payload: Esp32PlayUrlRequest) -> JSONResponse:
    source_url = _validate_remote_url(payload.url.strip())
    stream_url = f"/music/stream?url={source_url}"
    command = _set_command("play_url", source_url=source_url, stream_url=stream_url)
    notify_sync({"type": "command", **command}, target="esp32")
    return JSONResponse({"status": "ok", **command})


@router.post("/esp32/stop")
def stop_esp32_stream() -> JSONResponse:
    command = _set_command("stop")
    notify_sync({"type": "command", **command}, target="esp32")
    return JSONResponse({"status": "ok", **command})


@router.get("/esp32/state")
def get_esp32_state() -> dict[str, object]:
    with _state_lock:
        return dict(_latest_state)


@router.post("/esp32/state")
def set_esp32_state(payload: Esp32StateUpdateRequest) -> JSONResponse:
    state = _update_state(
        state=payload.state,
        file=payload.file,
        source=payload.source,
        device_ip=payload.device_ip,
        version=_command_version,
    )
    notify_sync({"type": "state", **state}, target="dashboard")
    return JSONResponse({"status": "ok", **state})


@router.post("/upload")
async def upload_music(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".mp3"):
        raise HTTPException(status_code=400, detail="Only .mp3 files are accepted")
    safe_name = _safe_name(file.filename)
    content = await file.read()

    if USE_BLOB:
        blob_store.upload(safe_name, content)
        log.info("Uploaded to blob: %s (%d bytes)", safe_name, len(content))
    else:
        _ensure_upload_dir()
        dest_path = os.path.join(UPLOAD_DIR, safe_name)
        with open(dest_path, "wb") as handle:
            handle.write(content)

    notify_sync({"type": "tracks", "tracks": _list_mp3()}, target="all")
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
    safe_name = _safe_name(filename)

    if USE_BLOB:
        blob_url = blob_store.get_download_url(safe_name)
        if not blob_url:
            raise HTTPException(status_code=404, detail="File not found")
        # Stream the file from Vercel Blob
        try:
            upstream = requests.get(blob_url, stream=True, timeout=15)
            upstream.raise_for_status()
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"Blob fetch failed: {exc}") from exc

        def blob_iterator() -> AsyncIterator[bytes]:
            for chunk in upstream.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        return StreamingResponse(blob_iterator(), media_type="audio/mpeg",
                                 headers={"Accept-Ranges": "bytes"})

    _ensure_upload_dir()
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
