"""Vercel Blob storage adapter for persistent MP3 file storage.

On Vercel serverless, /tmp is ephemeral and not shared across invocations.
This module uses the Vercel Blob REST API to persist uploaded MP3 files.

Requires BLOB_READ_WRITE_TOKEN environment variable (from Vercel Blob store).
"""

from __future__ import annotations

import os
import logging
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

BLOB_API = "https://blob.vercel-storage.com"
_TOKEN: str | None = os.environ.get("BLOB_READ_WRITE_TOKEN")
BLOB_PREFIX = "music/"


def is_available() -> bool:
    return bool(_TOKEN)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}


def upload(filename: str, content: bytes) -> str:
    """Upload file to Vercel Blob. Returns the blob URL."""
    safe = os.path.basename(filename)
    pathname = f"{BLOB_PREFIX}{safe}"
    resp = httpx.put(
        f"{BLOB_API}/{quote(pathname, safe='/')}",
        content=content,
        headers={
            **_headers(),
            "x-api-version": "7",
            "Content-Type": "audio/mpeg",
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    log.info("Blob upload: %s -> %s (%d bytes)", safe, data.get("url"), len(content))
    return data["url"]


def list_files() -> list[dict]:
    """List all MP3 blobs. Returns list of {pathname, url, size}."""
    results = []
    cursor: str | None = None
    while True:
        params: dict[str, str] = {"prefix": BLOB_PREFIX, "limit": "100"}
        if cursor:
            params["cursor"] = cursor
        resp = httpx.get(
            BLOB_API,
            params=params,
            headers={**_headers(), "x-api-version": "7"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        for blob in data.get("blobs", []):
            pn = blob.get("pathname", "")
            if pn.lower().endswith(".mp3"):
                results.append({
                    "pathname": pn,
                    "url": blob["url"],
                    "size": blob.get("size", 0),
                })
        cursor = data.get("cursor")
        if not data.get("hasMore") or not cursor:
            break
    return results


def list_mp3_names() -> list[str]:
    """Return sorted list of MP3 filenames (without prefix)."""
    blobs = list_files()
    names = []
    for b in blobs:
        name = b["pathname"].removeprefix(BLOB_PREFIX)
        if name:
            names.append(name)
    return sorted(names)


def get_download_url(filename: str) -> str | None:
    """Get the blob URL for a specific file."""
    safe = os.path.basename(filename)
    target = f"{BLOB_PREFIX}{safe}"
    for blob in list_files():
        if blob["pathname"] == target:
            return blob["url"]
    return None


def delete(filename: str) -> bool:
    """Delete a blob by filename."""
    url = get_download_url(filename)
    if not url:
        return False
    resp = httpx.post(
        f"{BLOB_API}/delete",
        json={"urls": [url]},
        headers={**_headers(), "x-api-version": "7"},
        timeout=15,
    )
    resp.raise_for_status()
    log.info("Blob deleted: %s", filename)
    return True
