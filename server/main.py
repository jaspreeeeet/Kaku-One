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

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine.animator import animator
from engine.expressions import EXPRESSIONS, invalidate_animation_cache
from config import HOST, PORT, ASSETS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await animator.start()
    yield
    await animator.stop()


app = FastAPI(
    title="MimiClaw Expression Server",
    description="Dynamic MJPEG expression streaming for ESP32-S3 round AMOLED",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Vercel frontend and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
                # Send a keep-alive comment to prevent client timeout
                yield b"--frame\r\nContent-Type: text/plain\r\n\r\n\r\n"
                continue

            content_length = len(frame)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(content_length).encode() + b"\r\n"
                b"\r\n" + frame + b"\r\n"
            )
    except (asyncio.CancelledError, GeneratorExit):
        pass


@app.get("/stream", summary="MJPEG live stream")
async def stream():
    """
    Multipart MJPEG stream.
    Open directly in browser or use as <img src="/stream">.
    ESP32 connects here to receive expression frames.
    """
    queue = animator.subscribe()

    async def cleanup():
        try:
            async for chunk in _mjpeg_generator(queue):
                yield chunk
        finally:
            animator.unsubscribe(queue)

    return StreamingResponse(
        cleanup(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
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
    return {"expression": animator.current_expression}


@app.get("/expressions", summary="List all expressions")
async def list_expressions():
    return {"expressions": list(EXPRESSIONS.keys())}


# ── status ─────────────────────────────────────────────────────────────────────

@app.get("/api/status", summary="Server status")
async def api_status():
    animation = await animator.get_animation_config()
    return {
        "status": "running",
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


# ── dashboard ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    html_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse(
        "<h1>Dashboard not found</h1>"
        "<p>Run the server from the <code>server/</code> directory.</p>"
    )


# ── entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
