"""
Expression registry — maps expression names to animation folders.

Each expression has pre-rendered JPEG frame sequences stored in
  assets/animations/{folder_name}/frame_0000.jpg, frame_0001.jpg, ...

Source MJPEG files:
  idle.mjpeg      → idle      (145 frames)
  cry.mjpeg       → sad       (145 frames)
  Executed.mjpeg  → happy     (145 frames)
  Surprise.mjpeg  → surprised (145 frames)
  thinking.mjpeg  → thinking  (145 frames)
  talking.mjpeg   → talking   (145 frames)
  sleeping.mjpeg  → sleeping  (145 frames)
  wake-up.mjpeg   → wakeup    (52 frames)
"""

from __future__ import annotations

import os
import logging
from functools import lru_cache

from config import ASSETS_DIR

log = logging.getLogger(__name__)

ANIMATIONS_DIR = os.path.join(ASSETS_DIR, "animations")


# Each expression maps to a subfolder name inside assets/animations/
# and a looping flag (True = loop continuously, False = play once then hold last frame)
EXPRESSIONS: dict[str, dict] = {
    "idle":      {"folder": "idle",      "loop": True},
    "happy":     {"folder": "happy",     "loop": True},
    "sad":       {"folder": "sad",       "loop": True},
    "surprised": {"folder": "surprised", "loop": True},
    "thinking":  {"folder": "thinking",  "loop": True},
    "talking":   {"folder": "talking",   "loop": True},
    "sleeping":  {"folder": "sleeping",  "loop": True},
    "wakeup":    {"folder": "wakeup",    "loop": False},
    # Aliases — reuse existing animations for similar emotions
    "angry":       {"folder": "sad",       "loop": True},
    "confused":    {"folder": "thinking",  "loop": True},
    "excited":     {"folder": "happy",     "loop": True},
    "smug":        {"folder": "happy",     "loop": True},
    "embarrassed": {"folder": "surprised", "loop": True},
}

DEFAULT_EXPRESSION = "idle"


@lru_cache(maxsize=32)
def load_animation_frames(folder: str) -> list[bytes]:
    """
    Load all JPEG frames for an animation folder into memory.
    Frames are sorted alphabetically (frame_0000.jpg, frame_0001.jpg, ...).
    Returns list of raw JPEG bytes.
    """
    anim_dir = os.path.join(ANIMATIONS_DIR, folder)
    if not os.path.isdir(anim_dir):
        log.warning("Animation folder not found: %s", anim_dir)
        return []

    frame_files = sorted(
        f for f in os.listdir(anim_dir)
        if f.lower().endswith(".jpg")
    )

    frames = []
    for fname in frame_files:
        path = os.path.join(anim_dir, fname)
        with open(path, "rb") as f:
            frames.append(f.read())

    log.info("Loaded %d frames for animation '%s'", len(frames), folder)
    return frames


def invalidate_animation_cache() -> None:
    """Call after adding/modifying animation frames."""
    load_animation_frames.cache_clear()
