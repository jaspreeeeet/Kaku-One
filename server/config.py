"""Server configuration."""
import os


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))

# Display canvas size — matches 1.43" round AMOLED (466x466)
CANVAS_WIDTH  = 466
CANVAS_HEIGHT = 466
CANVAS_SIZE   = (CANVAS_WIDTH, CANVAS_HEIGHT)

# MJPEG stream settings
STREAM_FPS      = _int_env("MIMI_STREAM_FPS", 12, 1, 60)         # frames per second
FRAME_QUALITY   = _int_env("MIMI_FRAME_QUALITY", 82, 1, 100)     # JPEG quality (0-100)

# Transition — cross-fade frames between expressions
TRANSITION_FRAMES = _int_env("MIMI_TRANSITION_FRAMES", 5, 0, 60)

# Asset directories
BASE_DIR   = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# Server
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 8000))

# External integration targets
ESP32WINAMP_BASE_URL = os.getenv("ESP32WINAMP_BASE_URL", "").rstrip("/")
ESP32WINAMP_TIMEOUT_S = _float_env("ESP32WINAMP_TIMEOUT_S", 15.0, 1.0, 120.0)
