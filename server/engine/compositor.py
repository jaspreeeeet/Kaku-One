"""
Image compositor — layers PNG sprites onto a 466×466 canvas and outputs JPEG bytes.

Layer order (bottom → top):
  1. base/face.png        — skin+hair base
  2. eyes/{name}.png      — expression-specific eyes
  3. mouths/{name}.png    — expression-specific mouth
  4. extras/blush.png     — optional blush cheeks
  5. Circular mask applied to match round AMOLED bezel
"""

from __future__ import annotations

import io
import os
import logging
from functools import lru_cache
from PIL import Image, ImageDraw

from config import CANVAS_SIZE, ASSETS_DIR, FRAME_QUALITY

log = logging.getLogger(__name__)

# ── asset loader ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def _load(subfolder: str, name: str) -> Image.Image:
    """Load a PNG asset, resize to canvas, cache in memory. Returns transparent if missing."""
    path = os.path.join(ASSETS_DIR, subfolder, f"{name}.png")
    if os.path.exists(path):
        try:
            img = Image.open(path).convert("RGBA")
            if img.size != CANVAS_SIZE:
                img = img.resize(CANVAS_SIZE, Image.LANCZOS)
            return img
        except Exception as e:
            log.warning("Failed to load asset %s: %s", path, e)
    else:
        log.debug("Asset not found: %s — using transparent placeholder", path)
    return Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))


def invalidate_asset_cache() -> None:
    """Call after uploading new assets to force reload."""
    _load.cache_clear()


# ── circular mask ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _circular_mask() -> Image.Image:
    mask = Image.new("L", CANVAS_SIZE, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([0, 0, CANVAS_SIZE[0] - 1, CANVAS_SIZE[1] - 1], fill=255)
    return mask


# ── compositor ───────────────────────────────────────────────────────────────

def composite_frame(
    expression_def: dict,
    eyes_override: str | None = None,
    mouth_override: str | None = None,
) -> bytes:
    """
    Render one JPEG frame for the given expression definition.

    Args:
        expression_def:  dict from expressions.EXPRESSIONS
        eyes_override:   force a specific eyes asset name (used for blink)
        mouth_override:  force a specific mouth asset name (used for talking cycle)

    Returns:
        Raw JPEG bytes ready to send over MJPEG stream.
    """
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))

    # Layer 1 — base face
    base = _load("base", "face")
    canvas = Image.alpha_composite(canvas, base)

    # Layer 2 — eyes
    eyes_name = eyes_override or expression_def.get("eyes", "eyes_open")
    eyes = _load("eyes", eyes_name)
    canvas = Image.alpha_composite(canvas, eyes)

    # Layer 3 — mouth
    mouth_name = mouth_override or expression_def.get("mouth", "mouth_neutral")
    mouth = _load("mouths", mouth_name)
    canvas = Image.alpha_composite(canvas, mouth)

    # Layer 4 — blush (optional)
    if expression_def.get("blush", False):
        blush = _load("extras", "blush")
        canvas = Image.alpha_composite(canvas, blush)

    # Apply circular mask so corners are transparent
    result = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    result.paste(canvas, mask=_circular_mask())

    # Flatten to black background → JPEG
    rgb = Image.new("RGB", CANVAS_SIZE, (0, 0, 0))
    rgb.paste(result, mask=result.split()[3])

    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=FRAME_QUALITY, optimize=False)
    return buf.getvalue()
