"""
MimiClaw Expression Server — FastAPI entry point.

Endpoints:
  GET  /              → Web dashboard (HTML)
  GET  /stream        → MJPEG multipart stream (for browser <img> and ESP32 client)
  POST /expression    → Change current expression
  GET  /expression    → Current expression name
  GET  /expressions   → All available expression names
  GET  /api/status    → Server + animator status (JSON)
  POST /api/assets/upload → Upload new PNG sprite asset
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, UploadFile, File, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine.animator_runtime import animator
from engine.expressions import DEFAULT_EXPRESSION, EXPRESSIONS, invalidate_animation_cache, load_animation_frames
from config import HOST, PORT, ASSETS_DIR
from music.local_music import router as local_music_router, _ensure_upload_dir
from ws_manager import manager as ws_manager, set_event_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MJPEG_BOUNDARY = "frame"


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    set_event_loop(asyncio.get_running_loop())
    _ensure_upload_dir()
    log.info("Registered routes: %s", sorted(route.path for route in app.routes))
    if not os.environ.get("VERCEL"):
        await animator.start()
    yield
    if not os.environ.get("VERCEL"):
        await animator.stop()


app = FastAPI(
    title="MimiClaw Expression Server",
    description="Dynamic MJPEG expression streaming for ESP32-S3 round AMOLED",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow same-origin frontend and production dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mimiclaw-rust.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (dashboard assets)
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── request/response models ───────────────────────────────────────────────────

class ExpressionRequest(BaseModel):
    expression: str
    intensity: float = 1.0


class AnimationConfigRequest(BaseModel):
    stream_fps: int | None = Field(default=None, ge=1, le=60)
    transition_frames: int | None = Field(default=None, ge=0, le=60)


# ── MJPEG stream ──────────────────────────────────────────────────────────────

async def _mjpeg_generator(queue: asyncio.Queue):
    """Async generator that yields MJPEG multipart frames."""
    try:
        while True:
            try:
                frame: bytes = await asyncio.wait_for(queue.get(), timeout=3.0)
            except asyncio.TimeoutError:
                yield b": keep-alive\r\n\r\n"
                continue

            content_length = len(frame)
            yield (
                b"--" + MJPEG_BOUNDARY.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(content_length).encode() + b"\r\n"
                b"\r\n" + frame + b"\r\n"
            )
    except (asyncio.CancelledError, GeneratorExit):
        pass


@app.get("/stream", summary="MJPEG live stream")
async def stream(request: Request):
    """
    Multipart MJPEG stream.
    Open directly in browser or use as <img src="/stream">.
    ESP32 connects here to receive expression frames.
    """
    queue = animator.subscribe()

    async def cleanup():
        try:
            async for chunk in _mjpeg_generator(queue):
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            animator.unsubscribe(queue)

    return StreamingResponse(
        cleanup(),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, no-transform",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── expression control ────────────────────────────────────────────────────────

@app.post("/expression", summary="Set expression")
async def set_expression(req: ExpressionRequest):
    """Change the character's facial expression."""
    try:
        await animator.set_expression(req.expression)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "expression": req.expression}


@app.get("/expression", summary="Get current expression")
async def get_expression():
    expr_name = animator.current_expression
    expr_def = EXPRESSIONS.get(expr_name, EXPRESSIONS[DEFAULT_EXPRESSION])
    frames = load_animation_frames(expr_def["folder"])
    return {
        "expression": expr_name,
        "frames": len(frames),
        "loop": expr_def.get("loop", True),
    }


@app.get("/frame", summary="Single JPEG frame")
async def get_single_frame(expression: str | None = None, index: int = 0):
    """Return one JPEG frame. Stateless — works on Vercel serverless."""
    expr_name = expression or animator.current_expression
    if expr_name not in EXPRESSIONS:
        expr_name = DEFAULT_EXPRESSION
    expr_def = EXPRESSIONS[expr_name]
    frames = load_animation_frames(expr_def["folder"])
    if not frames:
        raise HTTPException(status_code=404, detail=f"No frames for '{expr_name}'")
    total = len(frames)
    loop = expr_def.get("loop", True)
    idx = index % total if loop else min(index, total - 1)
    return Response(
        content=frames[idx],
        media_type="image/jpeg",
        headers={
            "X-Frame-Count": str(total),
            "X-Loop": "1" if loop else "0",
        },
    )


@app.get("/expressions", summary="List all expressions")
async def list_expressions():
    return {"expressions": list(EXPRESSIONS.keys())}


# ── status ─────────────────────────────────────────────────────────────────────

@app.get("/api/status", summary="Server status")
async def api_status():
    animation = await animator.get_animation_config()
    return {
        "status": "running",
        "system": "mimiclaw",
        "current_expression": animator.current_expression,
        "available_expressions": list(EXPRESSIONS.keys()),
        "connected_clients": animator.subscriber_count,
        "animation": animation,
    }


@app.get("/api/animation", summary="Get animation settings")
async def get_animation_config():
    return await animator.get_animation_config()


@app.post("/api/animation", summary="Update animation settings")
async def set_animation_config(req: AnimationConfigRequest):
    payload = req.model_dump(exclude_none=True)
    if not payload:
        return await animator.get_animation_config()

    try:
        return await animator.set_animation_config(**payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── asset upload ───────────────────────────────────────────────────────────────

@app.get("/api/assets", summary="List animation assets")
async def list_assets():
    anim_dir = os.path.join(ASSETS_DIR, "animations")
    result: dict[str, int] = {}
    if os.path.isdir(anim_dir):
        for name in sorted(os.listdir(anim_dir)):
            folder = os.path.join(anim_dir, name)
            if os.path.isdir(folder):
                count = len([f for f in os.listdir(folder) if f.endswith(".jpg")])
                result[name] = count
    return {"animations": result}


ALLOWED_SUBFOLDERS = {"base", "eyes", "mouths", "extras"}

@app.post("/api/assets/upload", summary="Upload PNG sprite asset")
async def upload_asset(
    subfolder: str = Form(...),
    file: UploadFile = File(...),
):
    if subfolder not in ALLOWED_SUBFOLDERS:
        raise HTTPException(status_code=400, detail=f"Invalid subfolder. Must be one of: {ALLOWED_SUBFOLDERS}")
    if not file.filename or not file.filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only .png files are accepted")

    dest_dir = os.path.join(ASSETS_DIR, subfolder)
    os.makedirs(dest_dir, exist_ok=True)

    # Sanitize filename to prevent path traversal
    safe_name = os.path.basename(file.filename)
    dest_path = os.path.join(dest_dir, safe_name)

    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    rel_path = f"{subfolder}/{safe_name}"
    log.info("Asset uploaded: %s (%d bytes)", rel_path, len(content))
    invalidate_animation_cache()
    return {"status": "ok", "path": rel_path}


# ── health check ───────────────────────────────────────────────────────────────

@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


@app.get("/debug/routes", include_in_schema=False)
async def debug_routes():
    return {
        "routes": sorted(route.path for route in app.routes),
    }


# ── WebSocket endpoints ───────────────────────────────────────────────────────

@app.websocket("/ws/esp32")
async def ws_esp32(websocket: WebSocket):
    """WebSocket for ESP32 devices — replaces command polling and state POST."""
    from music.local_music import (
        _latest_command, _latest_state, _command_lock, _state_lock,
        _update_state, _command_version, _list_mp3,
    )
    await ws_manager.connect_esp32(websocket)
    try:
        with _command_lock:
            cmd = dict(_latest_command)
        with _state_lock:
            state = dict(_latest_state)
        tracks = _list_mp3()
        await websocket.send_json({"type": "command", **cmd})
        await websocket.send_json({"type": "state", **state})
        await websocket.send_json({"type": "tracks", "tracks": tracks})
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "state":
                _update_state(
                    state=data.get("state", "stopped"),
                    file=data.get("file", ""),
                    source=data.get("source", ""),
                    device_ip=data.get("device_ip", ""),
                    version=_command_version,
                )
                await ws_manager.broadcast_to_dashboards({"type": "state", **data})
    except (WebSocketDisconnect, Exception):
        await ws_manager.disconnect_esp32(websocket)


@app.websocket("/ws/dashboard")
async def ws_dashboard(websocket: WebSocket):
    """WebSocket for dashboard clients — replaces state/command polling."""
    from music.local_music import (
        _latest_command, _latest_state, _command_lock, _state_lock,
        _set_command, _list_mp3, _validate_remote_url,
    )
    await ws_manager.connect_dashboard(websocket)
    try:
        with _command_lock:
            cmd = dict(_latest_command)
        with _state_lock:
            state = dict(_latest_state)
        tracks = _list_mp3()
        await websocket.send_json({"type": "command", **cmd})
        await websocket.send_json({"type": "state", **state})
        await websocket.send_json({"type": "tracks", "tracks": tracks})
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "command":
                action = data.get("action", "")
                file = data.get("file", "")
                source_url = data.get("source_url", "")
                stream_url = data.get("stream_url", "")
                if action == "play_url" and source_url:
                    source_url = _validate_remote_url(source_url)
                    stream_url = f"/music/stream?url={source_url}"
                cmd = _set_command(action, file=file, source_url=source_url,
                                   stream_url=stream_url)
                await ws_manager.broadcast_to_esp32({"type": "command", **cmd})
                await ws_manager.broadcast_to_dashboards({"type": "command", **cmd})
    except (WebSocketDisconnect, Exception):
        await ws_manager.disconnect_dashboard(websocket)


# ── dashboard ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    html_path = os.path.join(STATIC_DIR, "index-v2.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse(
        "<h1>Dashboard not found</h1>"
        "<p>Run the server from the <code>server/</code> directory.</p>"
    )


# ── entrypoint ────────────────────────────────────────────────────────────────

@app.get("/app-v2.js", include_in_schema=False)
async def app_v2():
    return FileResponse(os.path.join(STATIC_DIR, "app-v2.js"), media_type="application/javascript")


@app.get("/style-v2.css", include_in_schema=False)
async def style_v2():
    return FileResponse(os.path.join(STATIC_DIR, "style-v2.css"), media_type="text/css")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    return FileResponse(os.path.join(STATIC_DIR, "favicon.svg"), media_type="image/svg+xml")


mimiclaw_router = APIRouter(prefix="/mimiclaw", tags=["mimiclaw"])


@mimiclaw_router.get("/stream")
async def namespaced_stream(request: Request):
    return await stream(request)


@mimiclaw_router.get("/expression")
async def namespaced_get_expression():
    return await get_expression()


@mimiclaw_router.post("/expression")
async def namespaced_set_expression(req: ExpressionRequest):
    return await set_expression(req)


@mimiclaw_router.get("/expressions")
async def namespaced_list_expressions():
    return await list_expressions()


@mimiclaw_router.get("/frame")
async def namespaced_get_frame(expression: str | None = None, index: int = 0):
    return await get_single_frame(expression, index)


@mimiclaw_router.get("/api/status")
async def namespaced_status():
    return await api_status()


@mimiclaw_router.get("/api/animation")
async def namespaced_get_animation():
    return await get_animation_config()


@mimiclaw_router.post("/api/animation")
async def namespaced_set_animation(req: AnimationConfigRequest):
    return await set_animation_config(req)


app.include_router(mimiclaw_router)
app.include_router(local_music_router)


@app.get("/api/systems", summary="Integration status")
async def systems_status():
    return {
        "mimiclaw": await api_status(),
        "esp32winamp": {
            "configured": True,
            "proxy_prefix": "/music",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
