"""
Runtime-safe animator for MJPEG streaming.
"""

from __future__ import annotations

import asyncio
import io
import logging

from .expressions import DEFAULT_EXPRESSION, EXPRESSIONS, load_animation_frames
from config import FRAME_QUALITY, STREAM_FPS, TRANSITION_FRAMES

log = logging.getLogger(__name__)


class Animator:
    def __init__(self) -> None:
        self._expr: str = DEFAULT_EXPRESSION
        self._prev_expr: str | None = None
        self._transition_remaining: int = 0
        self._subscribers: list[asyncio.Queue[bytes]] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stream_fps: int = STREAM_FPS
        self._transition_frames: int = TRANSITION_FRAMES
        self._frame_idx: int = 0
        self._prev_frame_idx: int = 0
        self._latest_frame: bytes | None = None

    @property
    def current_expression(self) -> str:
        return self._expr

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def set_expression(self, name: str) -> None:
        if name not in EXPRESSIONS:
            raise ValueError(f"Unknown expression '{name}'. Available: {list(EXPRESSIONS.keys())}")

        async with self._lock:
            if name != self._expr:
                self._prev_expr = self._expr
                self._prev_frame_idx = self._frame_idx
                self._expr = name
                self._frame_idx = 0
                self._transition_remaining = self._transition_frames
                log.info("Expression changed: %s -> %s", self._prev_expr, name)

    async def get_animation_config(self) -> dict[str, int]:
        async with self._lock:
            return {
                "stream_fps": self._stream_fps,
                "transition_frames": self._transition_frames,
            }

    async def set_animation_config(
        self,
        *,
        stream_fps: int | None = None,
        transition_frames: int | None = None,
    ) -> dict[str, int]:
        async with self._lock:
            if stream_fps is not None:
                self._stream_fps = max(1, min(60, stream_fps))
            if transition_frames is not None:
                self._transition_frames = max(0, min(60, transition_frames))
                if self._transition_remaining > self._transition_frames:
                    self._transition_remaining = self._transition_frames
            return {
                "stream_fps": self._stream_fps,
                "transition_frames": self._transition_frames,
            }

    def subscribe(self) -> asyncio.Queue[bytes]:
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=3)
        self._subscribers.append(queue)
        if self._latest_frame is not None:
            try:
                queue.put_nowait(self._latest_frame)
            except asyncio.QueueFull:
                pass
        return queue

    def unsubscribe(self, queue: asyncio.Queue[bytes]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def start(self) -> None:
        for expression_def in EXPRESSIONS.values():
            load_animation_frames(expression_def["folder"])
        self._task = asyncio.create_task(self._loop(), name="animator")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            frame_start = asyncio.get_running_loop().time()

            async with self._lock:
                expr_name = self._expr
                prev_name = self._prev_expr
                transition_remaining = self._transition_remaining
                stream_fps = self._stream_fps

            expression_def = EXPRESSIONS[expr_name]
            frames = load_animation_frames(expression_def["folder"])
            if not frames:
                await asyncio.sleep(1.0 / stream_fps)
                continue

            if expression_def.get("loop", True):
                self._frame_idx = self._frame_idx % len(frames)
            else:
                self._frame_idx = min(self._frame_idx, len(frames) - 1)

            current_frame = frames[self._frame_idx]

            if transition_remaining > 0 and prev_name:
                prev_def = EXPRESSIONS.get(prev_name, EXPRESSIONS[DEFAULT_EXPRESSION])
                prev_frames = load_animation_frames(prev_def["folder"])
                if prev_frames:
                    prev_idx = self._prev_frame_idx % len(prev_frames)
                    frame_bytes = self._blend_frames(prev_frames[prev_idx], current_frame, transition_remaining)
                    self._prev_frame_idx += 1
                else:
                    frame_bytes = current_frame
                async with self._lock:
                    self._transition_remaining = max(0, transition_remaining - 1)
            else:
                frame_bytes = current_frame

            self._frame_idx += 1
            self._latest_frame = frame_bytes
            await self._broadcast(frame_bytes)

            elapsed = asyncio.get_running_loop().time() - frame_start
            sleep_s = (1.0 / stream_fps) - elapsed
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)

    def _blend_frames(self, from_jpeg: bytes, to_jpeg: bytes, remaining: int) -> bytes:
        from PIL import Image

        transition_total = max(1, self._transition_frames)
        alpha = 1.0 - (remaining / transition_total)
        img_from = Image.open(io.BytesIO(from_jpeg)).convert("RGB")
        img_to = Image.open(io.BytesIO(to_jpeg)).convert("RGB")
        blended = Image.blend(img_from, img_to, alpha)

        buf = io.BytesIO()
        blended.save(buf, format="JPEG", quality=FRAME_QUALITY, optimize=False)
        return buf.getvalue()

    async def _broadcast(self, frame: bytes) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                pass


animator = Animator()
