"""WebSocket connection manager for real-time ESP32 <-> Dashboard communication.

Replaces HTTP polling for /music/esp32/command and /music/esp32/state with
persistent WebSocket connections. REST endpoints are preserved as fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket

log = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


class ConnectionManager:
    """Track WebSocket connections for ESP32 devices and dashboard clients."""

    def __init__(self) -> None:
        self.esp32_clients: Set[WebSocket] = set()
        self.dashboard_clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect_esp32(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.esp32_clients.add(ws)
        log.info("ESP32 WS connected (%d total)", len(self.esp32_clients))

    async def connect_dashboard(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.dashboard_clients.add(ws)
        log.info("Dashboard WS connected (%d total)", len(self.dashboard_clients))

    async def disconnect_esp32(self, ws: WebSocket) -> None:
        async with self._lock:
            self.esp32_clients.discard(ws)
        log.info("ESP32 WS disconnected (%d remaining)", len(self.esp32_clients))

    async def disconnect_dashboard(self, ws: WebSocket) -> None:
        async with self._lock:
            self.dashboard_clients.discard(ws)
        log.info("Dashboard WS disconnected (%d remaining)", len(self.dashboard_clients))

    async def broadcast_to_esp32(self, message: dict) -> None:
        data = json.dumps(message)
        async with self._lock:
            clients = list(self.esp32_clients)
        for ws in clients:
            try:
                await ws.send_text(data)
            except Exception:
                async with self._lock:
                    self.esp32_clients.discard(ws)

    async def broadcast_to_dashboards(self, message: dict) -> None:
        data = json.dumps(message)
        async with self._lock:
            clients = list(self.dashboard_clients)
        for ws in clients:
            try:
                await ws.send_text(data)
            except Exception:
                async with self._lock:
                    self.dashboard_clients.discard(ws)

    async def broadcast_to_all(self, message: dict) -> None:
        await self.broadcast_to_esp32(message)
        await self.broadcast_to_dashboards(message)


manager = ConnectionManager()


def notify_sync(message: dict, target: str = "all") -> None:
    """Schedule an async broadcast from synchronous code (REST handlers)."""
    if _loop is None or _loop.is_closed():
        return
    coro = {
        "esp32": manager.broadcast_to_esp32,
        "dashboard": manager.broadcast_to_dashboards,
        "all": manager.broadcast_to_all,
    }.get(target, manager.broadcast_to_all)(message)
    asyncio.run_coroutine_threadsafe(coro, _loop)
