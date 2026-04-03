# AI Agent Handoff

## Purpose
This document gives the next agent enough context to continue work on the MimiClaw + ESP32 Winamp system without re-discovering the repo structure, deployment shape, or current blockers.

**Last updated: April 2026 — WebSocket migration completed.**

---

## CRITICAL — READ THIS FIRST

### Do NOT break these invariants:
1. **All REST endpoints must remain functional** — WebSocket was added *alongside* REST, not replacing it. REST is the fallback when WS is unavailable (e.g., Vercel serverless).
2. **ESP32 Winamp has automatic HTTP↔WS fallback** — `Task_RemoteCommand` checks `s_ws_connected` to decide whether to use WS or HTTP polling. Do not remove either path.
3. **Frontend `app-v2.js` has the same fallback** — the `setInterval` for `refreshEsp32State()` skips when `_wsConnected` is true. Do not remove the REST polling code.
4. **`audio.connecttohost(url)` in ESP32 Winamp MUST remain HTTP** — the ESP32-audioI2S library can only stream from HTTP URLs, not WebSocket.
5. **MJPEG `/stream` endpoint MUST remain HTTP** — it's a persistent push connection already, used by both `<img>` tags and `mjpeg_client.c` on the ESP32 agent.
6. **External APIs (Anthropic, Brave, Telegram, Feishu) are all HTTP** — do not try to WebSocket these.

---

## Repos And Local Paths

### 1. Mimiclaw repo (server + ESP32 agent firmware + frontend)
- **Local path:** `D:\mimiclaw`
- **Remote `origin`:** `https://github.com/jaspreeeeet/Kaku-One.git`
- **Remote `krishna`:** `https://github.com/iamkrishnagupta10/KakuOne.git`
- **Current branch:** `main`
- **Contains:** Python FastAPI server, static JS frontend, AND ESP32-S3 IDF firmware (agent)
- **Do NOT assume it is Python-only** — root-level `main/`, `components/`, `CMakeLists.txt`, `sdkconfig` are ESP-IDF firmware.

### 2. ESP32 Winamp (music player firmware — separate, no git remote set up)
- **Local path:** `D:\lastfinal test`
- **Uses:** Arduino framework + ESP-IDF components (LVGL, ESP32-audioI2S, TouchLib)
- **Backend it talks to:** `https://server-five-nu-67.vercel.app` (hardcoded in defines)
- **Not a git repo** — no `.git` directory

### 3. ESP32 Winamp (older copy, has git)
- **Local path:** `D:\Esp32Winamp`
- **Remote:** `https://github.com/rajeev-hash/Esp32winamp.git`
- **Note:** `D:\lastfinal test` is the active development copy. `D:\Esp32Winamp` may be outdated.

---

## Live URLs

| What | URL |
|---|---|
| Frontend dashboard | `https://mimiclaw-rust.vercel.app` |
| Backend (Vercel) | `https://kaku-one-gamma.vercel.app` |
| Backend (alternate) | `https://server-five-nu-67.vercel.app` |

---

## System Architecture (3 devices, 1 server)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Python FastAPI Server                            │
│                    (Vercel / Render / local uvicorn)                │
│                                                                     │
│  REST endpoints (all kept):          WebSocket endpoints (new):     │
│  GET  /healthz                       WS /ws/esp32                   │
│  GET  /stream (MJPEG push)           WS /ws/dashboard               │
│  POST /expression                                                    │
│  GET  /expressions                   ws_manager.py manages both     │
│  GET  /api/status                    connection pools                │
│  POST /api/animation                                                 │
│  POST /api/assets/upload                                             │
│  GET  /music/list                                                    │
│  POST /music/upload                                                  │
│  GET  /music/{filename}                                              │
│  GET  /music/stream?url=...                                          │
│  GET  /music/esp32/command (kept for fallback)                       │
│  POST /music/esp32/command (kept, also notifies WS clients)          │
│  POST /music/esp32/state  (kept, also notifies WS clients)           │
│  POST /music/esp32/play-url (kept, also notifies WS clients)         │
│  POST /music/esp32/stop    (kept, also notifies WS clients)          │
└──────────┬──────────────────────┬──────────────────────┬────────────┘
           │                      │                      │
     HTTP MJPEG push         WS or REST             WS or REST
           │                      │                      │
           ▼                      ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
│ ESP32-S3 Agent   │  │ ESP32 Winamp     │  │ Browser Dashboard    │
│ (mimiclaw)       │  │ (lastfinal test) │  │ (app-v2.js)          │
│                  │  │                  │  │                      │
│ mjpeg_client.c   │  │ WS client →      │  │ WS client →          │
│  → GET /stream   │  │  /ws/esp32       │  │  /ws/dashboard       │
│                  │  │  (auto-fallback  │  │  (auto-fallback      │
│ tool_expression  │  │   to HTTP poll)  │  │   to REST poll)      │
│  → POST /expr    │  │                  │  │                      │
│                  │  │ audio.connect    │  │ fetch() for uploads,  │
│ llm_proxy.c      │  │  tohost(HTTP)    │  │ one-time fetches     │
│  → Anthropic API │  │  (must stay HTTP)│  │                      │
│                  │  │                  │  │                      │
│ tool_web_search  │  │ WiFi scan/       │  │                      │
│  → Brave API     │  │ connect (HTTP)   │  │                      │
│                  │  │                  │  │                      │
│ telegram_bot.c   │  │                  │  │                      │
│  → Telegram API  │  │                  │  │                      │
└──────────────────┘  └──────────────────┘  └──────────────────────┘
```

---

## WebSocket Protocol (added April 2026)

### Endpoints
- `/ws/esp32` — ESP32 devices connect here
- `/ws/dashboard` — Browser dashboard connects here

### Message format (JSON text frames)
```json
// Command (dashboard → server → ESP32)
{"type": "command", "version": 5, "action": "play", "file": "song.mp3", "source_url": "", "stream_url": ""}

// State (ESP32 → server → dashboard)
{"type": "state", "state": "playing", "file": "song.mp3", "source": "local"}

// Track list (server → both, on change)
{"type": "tracks", "tracks": ["a.mp3", "b.mp3"]}
```

### On connect: server pushes current command, state, and track list immediately.

### Fallback behavior:
- **ESP32 Winamp:** `s_ws_connected` flag in `Task_RemoteCommand`. If false → uses `poll_remote_stream_command()` and `report_playback_state()` via HTTP.
- **Dashboard:** `_wsConnected` flag. If false → `setInterval` fires REST polling every 2s.
- **REST handlers also notify WS** — so mixed HTTP + WS clients stay in sync.

---

## File Map — What Does What

### Server (D:\mimiclaw\server\)

| File | Role | Safe to modify? |
|---|---|---|
| `main.py` | FastAPI app, all routes, WS endpoints | ⚠️ Careful — WS + REST coexist |
| `ws_manager.py` | WS connection manager (created April 2026) | Yes |
| `music/local_music.py` | Music REST routes + `notify_sync()` calls | ⚠️ Keep `notify_sync()` calls |
| `config.py` | Display/stream config (FPS, quality) | Yes |
| `engine/animator_runtime.py` | MJPEG frame generation | ⚠️ Core animation loop |
| `engine/expressions.py` | Expression definitions | Yes |
| `static/app-v2.js` | Dashboard frontend (WS + REST fallback) | ⚠️ Keep both code paths |
| `static/index-v2.html` | Dashboard HTML | Yes |

### ESP32 Winamp (D:\lastfinal test\main\Winamp480x320\)

| File | Role | Safe to modify? |
|---|---|---|
| `Winamp480x320.cpp` | Everything — UI, WiFi, audio, WS client, HTTP client | ⚠️ Very dense, 2300+ lines |
| `ui.cpp / ui.h` | LVGL generated UI — do not hand-edit | ❌ Generated |

### ESP32 Agent (D:\mimiclaw\main\)

| File | Role | Safe to modify? |
|---|---|---|
| `mimi.c` | Entry point, task creation | ⚠️ Careful |
| `llm/llm_proxy.c` | Claude API client (HTTP) | Yes |
| `tools/tool_expression.c` | POST /expression (HTTP, keep as-is) | Yes |
| `tools/tool_web_search.c` | Brave Search (HTTP, keep as-is) | Yes |
| `gateway/ws_server.c` | Internal WS server on :18789 | ⚠️ Separate from backend WS |
| `display/mjpeg_client.c` | HTTP MJPEG streaming client | ⚠️ Must stay HTTP |
| `channels/telegram/telegram_bot.c` | Telegram long polling (HTTP) | Yes |
| `channels/feishu/feishu_bot.c` | Feishu WS client (already WS) | Yes |

---

## What changed in April 2026 (WebSocket migration)

### Created:
- `server/ws_manager.py` — connection pools for ESP32 + dashboard WS clients

### Modified:
- `server/main.py` — added `/ws/esp32`, `/ws/dashboard` endpoints
- `server/music/local_music.py` — added `notify_sync()` calls to 5 REST handlers
- `server/static/app-v2.js` — added WS client with reconnect, REST fallback kept
- `D:\lastfinal test\main\Winamp480x320\Winamp480x320.cpp` — added `esp_websocket_client` WS client with HTTP fallback
- `D:\lastfinal test\idf_component.yml` — added `espressif/esp_websocket_client` dependency

### NOT modified (intentionally):
- ESP32 agent firmware (mimiclaw `main/`) — all its HTTP calls are one-shot, not polling
- MJPEG stream — already push, not polling
- External API calls — can't change third-party APIs

---

## Tests

```bash
cd D:\mimiclaw\server
python -m pytest -q tests/
# Expected: 11 passed, 3 skipped
```

---

## Build & Deploy

### Server
- **Local:** `cd D:\mimiclaw\server && uvicorn main:app --host 0.0.0.0 --port 8000`
- **Vercel:** auto-deploys from git push (but WS won't work on Vercel serverless — REST fallback kicks in)
- **Render / VPS:** WebSocket fully works

### ESP32 Winamp
```bash
cd "D:\lastfinal test"
idf.py build
idf.py -p COMx flash monitor
```
- Backend URL hardcoded: `server-five-nu-67.vercel.app:443`

### ESP32 Agent (mimiclaw)
```bash
cd D:\mimiclaw
idf.py build
idf.py -p COMx flash monitor
```

---

## Known Issues

1. **Vercel does NOT support WebSocket** — the WS endpoints only work on non-serverless hosts (Render, VPS, local). REST fallback handles Vercel deployments.
2. **MP3 uploads on Vercel are ephemeral** — `/tmp/uploads` is wiped on cold start. Use Vercel Blob or a persistent backend for production.
3. **ESP32 Winamp `D:\lastfinal test` has no git** — changes are only on disk. Back up manually.
4. **Two backend URLs exist** — `kaku-one-gamma.vercel.app` and `server-five-nu-67.vercel.app`. ESP32 Winamp uses the latter.

---

## Safe Assumptions
- Do not assume `mimiclaw` is only frontend/backend — it also has ESP32 firmware
- Do not assume Vercel deployment matches latest local code
- Do not assume WebSocket is always connected — always keep REST fallback
- Do not assume browser playback = ESP32 playback (different devices)
- Do not remove REST endpoints — they are the fallback for WS
- Do not change `audio.connecttohost()` to WebSocket — the library requires HTTP URLs

## Files Most Worth Reading First
- `D:\mimiclaw\server\main.py`
- `D:\mimiclaw\server\music\local_music.py`
- `D:\mimiclaw\server\static\app-v2.js`
- `D:\Esp32Winamp\main\Winamp480x320\Winamp480x320.cpp`

