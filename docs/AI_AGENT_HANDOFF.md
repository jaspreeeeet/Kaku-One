# AI Agent Handoff

## Purpose
This document gives the next agent enough context to continue work on the MimiClaw + ESP32 Winamp system without re-discovering the repo structure, deployment shape, or current blockers.

## Repos And Local Paths

### 1. Mimiclaw repo
- Local path: `D:\mimiclaw`
- Primary use: backend server + static frontend
- Important note: this repo also contains ESP-IDF firmware folders at the root (`main`, `components`, `sdkconfig`, etc.), so do not assume it is Python-only.

### 2. ESP32 Winamp repo
- Local path: `D:\Esp32Winamp`
- Primary use: separate ESP32 music player firmware project

## Git Remotes And Current Branches

### Mimiclaw
- Current local branch: `codex/update-backend-url`
- Remote `krishna`: `https://github.com/iamkrishnagupta10/KakuOne.git`
- Remote `origin`: `https://github.com/jaspreeeeet/Kaku-One`
- Important note: latest Mimiclaw work was pushed to `krishna/main` from local branch `codex/update-backend-url`
- Important note: pushes to both remotes may fail if tokens/credentials expire

### ESP32 Winamp
- Current branch: `main`
- Remote `origin`: `https://github.com/rajeev-hash/Esp32winamp.git`

## Live URLs

### Frontend
- Main alias: `https://mimiclaw-rust.vercel.app`

### Backend currently being used by frontend and ESP32 firmware
- `https://kaku-one-gamma.vercel.app`

## Current Architecture

### Frontend
- Static frontend served on Vercel
- Main files:
  - `D:\mimiclaw\server\static\index.html`
  - `D:\mimiclaw\server\static\index-v2.html`
  - `D:\mimiclaw\server\static\app-v2.js`
  - `D:\mimiclaw\server\static\style-v2.css`

### Backend
- FastAPI app
- Main file: `D:\mimiclaw\server\main.py`
- Music routes: `D:\mimiclaw\server\music\local_music.py`

### ESP32 firmware in separate repo
- Main file: `D:\Esp32Winamp\main\Winamp480x320\Winamp480x320.cpp`

## Backend Routes Expected In Code

### Mimiclaw routes
- `/healthz`
- `/debug/routes`
- `/stream`
- `/expression`
- `/expressions`
- `/api/status`
- `/api/animation`
- `/api/assets`
- `/api/assets/upload`
- `/mimiclaw/*`
- `/api/systems`

### Music routes
- `/music/list`
- `/music/health`
- `/music/upload`
- `/music/stream?url=...`
- `/music/{filename}`

### ESP32 remote command routes added in newer code
- `/music/esp32/command`
- `/music/esp32/play-url`

## Current Live Runtime State

These checks were confirmed during the latest session:

- `https://kaku-one-gamma.vercel.app/healthz` -> `200`
- `https://kaku-one-gamma.vercel.app/music/list` -> `200`, but returns `{"tracks":[]}`
- `https://kaku-one-gamma.vercel.app/music/health` -> `200`, but returns `{"status":"ok","tracks":0}`
- `https://kaku-one-gamma.vercel.app/music/esp32/command` -> `404`
- `https://kaku-one-gamma.vercel.app/music/esp32/play-url` -> `404`

## What This Means

### Good
- Backend is publicly reachable on the current Vercel-backed host
- Health route works
- Music list route exists

### Broken
- Uploaded MP3s are not available as persistent tracks on the live deployment
- ESP32 remote command endpoints are not present on the currently deployed backend

### Likely reason
There is a deployment/version mismatch:
- one deployed version includes Vercel upload handling (`/tmp/uploads`)
- a different local/newer version includes the ESP32 command endpoints
- the live deployment does not currently have both fixes together

## Frontend Behavior

File: `D:\mimiclaw\server\static\app-v2.js`

Current behavior:
- Mimiclaw calls go to the configured `API_BASE`
- Music catalog loads from `/music/list`
- Clicking a track plays it in the browser audio element
- "Play From URL" does two things:
  - attempts `POST /music/esp32/play-url`
  - also sets the browser audio element to `/music/stream?url=...`

Important note:
- browser playback is not the same thing as ESP32 playback
- the actual goal is ESP32 playback

## ESP32 Winamp Firmware Behavior

File: `D:\Esp32Winamp\main\Winamp480x320\Winamp480x320.cpp`

Current configured backend:
- `BACKEND_SCHEME "https"`
- `BACKEND_HOST "kaku-one-gamma.vercel.app"`
- `BACKEND_PORT 443`

Actual URLs used by firmware:
- `https://kaku-one-gamma.vercel.app/music/list`
- `https://kaku-one-gamma.vercel.app/music/<filename>`
- `https://kaku-one-gamma.vercel.app/music/esp32/command`
- when commanded remotely: `https://kaku-one-gamma.vercel.app/music/stream?url=...`

Current expected device behavior:
- WiFi connects
- firmware fetches `/music/list`
- because list is currently empty, AMOLED shows no songs / 0 songs
- remote URL play flow also fails because `/music/esp32/command` is 404

## Tests

### Command used
`python -m pytest -q D:\mimiclaw\server\tests`

### Latest result
- `11 passed, 3 skipped`

### What tests cover
- health route
- API shape
- namespaced mimiclaw routes
- expression roundtrip
- systems endpoint
- music upload/list/file serving
- MJPEG stream headers
- `/music/stream?url=...`
- ESP32 command endpoint logic in local code

### Important note
Local tests are green. Live deployment is still inconsistent with local code.

## Known Compile Fix In ESP32 Winamp Repo

If building `D:\Esp32Winamp` fails with:
- `'cleanup_value' was not declared in this scope`

Then the forward declaration fix is already applied in:
- `D:\Esp32Winamp\main\Winamp480x320\Winamp480x320.cpp`

## Recommended Next Steps For The Next Agent

1. Merge the two backend fixes into the same deployed version:
- Vercel-safe upload path handling
- ESP32 command endpoints

2. Verify live routes after deploy:
- `/music/list`
- `/music/health`
- `/music/esp32/command`
- `/music/esp32/play-url`

3. Test whether uploaded MP3s persist across requests on the actual hosting runtime

4. Decide whether music storage should stay on Vercel filesystem at all
- if persistence matters, object storage or a persistent backend is likely needed

5. Keep frontend/browser playback and ESP32 playback conceptually separate during debugging

## Safe Assumptions
- Do not assume `mimiclaw` is only frontend/backend; it also has ESP32 firmware folders
- Do not assume the live deployment matches the latest local branch
- Do not assume successful upload means persistent storage on Vercel
- Do not assume browser playback implies ESP32 playback works

## Files Most Worth Reading First
- `D:\mimiclaw\server\main.py`
- `D:\mimiclaw\server\music\local_music.py`
- `D:\mimiclaw\server\static\app-v2.js`
- `D:\Esp32Winamp\main\Winamp480x320\Winamp480x320.cpp`

