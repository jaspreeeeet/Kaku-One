"""
Extract individual JPEG frames from MJPEG animation files.

MJPEG format: concatenated JPEG images (each starts with FF D8, ends with FF D9).

Source files from reference project:
  cry.mjpeg      → sad
  Executed.mjpeg → happy
  idle.mjpeg     → idle
  sleeping.mjpeg → sleeping
  Surprise.mjpeg → surprised
  talking.mjpeg  → talking
  thinking.mjpeg → thinking
  wake-up.mjpeg  → wakeup

Each frame is resized to 466×466 and gets a circular mask applied
to match the round AMOLED display.
"""

import os
import io
import sys
from PIL import Image, ImageDraw

CANVAS_SIZE = (466, 466)
FRAME_QUALITY = 85

# Mapping: source MJPEG filename (without extension) → target expression folder name
MJPEG_MAP = {
    "idle":      "idle",
    "cry":       "sad",
    "Executed":  "happy",
    "Surprise":  "surprised",
    "thinking":  "thinking",
    "talking":   "talking",
    "sleeping":  "sleeping",
    "wake-up":   "wakeup",
}


def create_circular_mask(size):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([0, 0, size[0] - 1, size[1] - 1], fill=255)
    return mask


def extract_jpegs_from_mjpeg(data: bytes) -> list[bytes]:
    """Split raw MJPEG data into individual JPEG frames."""
    frames = []
    SOI = b'\xff\xd8'  # Start Of Image
    EOI = b'\xff\xd9'  # End Of Image

    pos = 0
    while pos < len(data):
        # Find next SOI marker
        start = data.find(SOI, pos)
        if start == -1:
            break
        # Find corresponding EOI marker
        end = data.find(EOI, start + 2)
        if end == -1:
            break
        end += 2  # include the EOI marker itself
        frames.append(data[start:end])
        pos = end

    return frames


def process_frame(jpeg_bytes: bytes, mask: Image.Image) -> bytes:
    """Resize frame to canvas, apply circular mask, encode as JPEG."""
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGBA")

    # Resize to canvas size
    if img.size != CANVAS_SIZE:
        img = img.resize(CANVAS_SIZE, Image.LANCZOS)

    # Apply circular mask — black outside the circle
    result = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    result.paste(img, mask=mask)

    # Flatten to RGB with black background
    rgb = Image.new("RGB", CANVAS_SIZE, (0, 0, 0))
    rgb.paste(result, mask=result.split()[3])

    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=FRAME_QUALITY, optimize=False)
    return buf.getvalue()


def main():
    if len(sys.argv) < 2:
        source_dir = r"E:\Rajeev\07_LVGL_Test\data\mjpeg"
    else:
        source_dir = sys.argv[1]

    output_dir = os.path.join(os.path.dirname(__file__), "assets", "animations")
    os.makedirs(output_dir, exist_ok=True)

    mask = create_circular_mask(CANVAS_SIZE)
    total_frames = 0

    for mjpeg_name, expr_name in MJPEG_MAP.items():
        src_path = os.path.join(source_dir, f"{mjpeg_name}.mjpeg")
        if not os.path.exists(src_path):
            print(f"  SKIP: {src_path} not found")
            continue

        print(f"  Processing {mjpeg_name}.mjpeg → {expr_name}/")

        with open(src_path, "rb") as f:
            raw = f.read()

        frames = extract_jpegs_from_mjpeg(raw)
        if not frames:
            print(f"    WARNING: No JPEG frames found in {src_path}")
            continue

        dest_dir = os.path.join(output_dir, expr_name)
        os.makedirs(dest_dir, exist_ok=True)

        for i, frame_data in enumerate(frames):
            processed = process_frame(frame_data, mask)
            frame_path = os.path.join(dest_dir, f"frame_{i:04d}.jpg")
            with open(frame_path, "wb") as f:
                f.write(processed)

        print(f"    Extracted {len(frames)} frames")
        total_frames += len(frames)

    print(f"\nDone! Total: {total_frames} frames across {len(MJPEG_MAP)} expressions")
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    main()
