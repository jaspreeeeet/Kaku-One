"""
Generate placeholder sprite assets for MimiClaw.

Draws simple anime-style face parts programmatically using Pillow.
Run this once before starting the server:

    cd server
    python assets/generate_placeholders.py

All images are 466×466 RGBA PNGs positioned to overlay correctly on the round face.
"""

from __future__ import annotations
import os
import math
from PIL import Image, ImageDraw, ImageFilter

W, H = 466, 466
CX, CY = W // 2, H // 2

# Face feature positions (tuned for anime proportions on a round 466x466 face)
EYE_Y          = 190          # vertical center of eyes
EYE_L_X        = 150          # left eye horizontal center
EYE_R_X        = 316          # right eye horizontal center
EYE_W          = 64           # eye width
EYE_H          = 50           # eye height (open)
PUPIL_W        = 32           # pupil width
PUPIL_H        = 38           # pupil height

MOUTH_Y        = 320          # mouth center Y
MOUTH_W        = 120          # mouth width (smile width)
MOUTH_H_OPEN   = 40           # mouth height when open

BLUSH_Y        = 235          # blush cheek Y
BLUSH_L_X      = 100          # left blush center
BLUSH_R_X      = 366          # right blush center
BLUSH_W        = 80           # blush ellipse width
BLUSH_H        = 30           # blush ellipse height

# Skin and hair colors
SKIN_COLOR  = (255, 224, 196, 255)
HAIR_COLOR  = (60,  40,  80,  255)
EYE_WHITE   = (255, 255, 255, 255)
EYE_IRIS    = (90,  60, 160, 255)    # purple iris
PUPIL_COLOR = (20,  10,  30, 255)
OUTLINE     = (40,  30,  50, 200)
BLUSH_COLOR = (255, 120, 140, 80)    # semi-transparent pink
LIP_COLOR   = (200,  90, 110, 255)


def new_canvas() -> tuple[Image.Image, ImageDraw.Draw]:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def save(img: Image.Image, folder: str, name: str) -> None:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}.png")
    img.save(path)
    print(f"  ✓ {path}")


def ellipse(draw: ImageDraw.Draw, cx: int, cy: int, rw: int, rh: int, **kwargs):
    draw.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], **kwargs)


# ── Base face ────────────────────────────────────────────────────────────────

def gen_face_base(folder: str) -> None:
    img, draw = new_canvas()

    # Hair (top half-ish, behind face)
    draw.ellipse([20, 10, W - 20, H - 60], fill=HAIR_COLOR)

    # Face skin circle
    draw.ellipse([30, 50, W - 30, H - 30], fill=SKIN_COLOR)

    # Ears
    ellipse(draw, 28, CY, 20, 28, fill=SKIN_COLOR, outline=OUTLINE, width=2)
    ellipse(draw, W - 28, CY, 20, 28, fill=SKIN_COLOR, outline=OUTLINE, width=2)

    # Some hair detail at top
    for x_off in range(-80, 90, 25):
        draw.ellipse([CX + x_off - 15, 8, CX + x_off + 15, 55], fill=HAIR_COLOR)

    # Side hair locks
    draw.polygon([(30, 100), (10, 280), (55, 260), (70, 120)], fill=HAIR_COLOR)
    draw.polygon([(W-30, 100), (W-10, 280), (W-55, 260), (W-70, 120)], fill=HAIR_COLOR)

    # Neck
    draw.rectangle([CX - 28, H - 60, CX + 28, H - 20], fill=SKIN_COLOR)

    save(img, folder, "face")


# ── Eyes ─────────────────────────────────────────────────────────────────────

def draw_open_eye(draw: ImageDraw.Draw, cx: int, cy: int, rw: int, rh: int) -> None:
    ellipse(draw, cx, cy, rw, rh, fill=EYE_WHITE, outline=OUTLINE, width=2)
    ellipse(draw, cx, cy + 2, PUPIL_W // 2, PUPIL_H // 2, fill=EYE_IRIS)
    ellipse(draw, cx, cy + 2, PUPIL_W // 4, PUPIL_H // 4, fill=PUPIL_COLOR)
    # Highlight
    ellipse(draw, cx - 8, cy - 8, 6, 6, fill=(255, 255, 255, 220))


def gen_eyes_open(folder: str) -> None:
    img, draw = new_canvas()
    for cx in (EYE_L_X, EYE_R_X):
        draw_open_eye(draw, cx, EYE_Y, EYE_W // 2, EYE_H // 2)
    save(img, folder, "eyes_open")


def gen_eyes_closed(folder: str) -> None:
    img, draw = new_canvas()
    for cx in (EYE_L_X, EYE_R_X):
        # Closed = thin horizontal arc
        draw.arc([cx - EYE_W // 2, EYE_Y - 8, cx + EYE_W // 2, EYE_Y + 24],
                 start=200, end=340, fill=OUTLINE, width=4)
    save(img, folder, "eyes_closed")


def gen_eyes_happy(folder: str) -> None:
    img, draw = new_canvas()
    for cx in (EYE_L_X, EYE_R_X):
        # Happy = upward curve (U-shape compressed)
        draw.arc([cx - EYE_W // 2, EYE_Y - 20, cx + EYE_W // 2, EYE_Y + 20],
                 start=0, end=180, fill=OUTLINE, width=5)
    save(img, folder, "eyes_happy")


def gen_eyes_sad(folder: str) -> None:
    img, draw = new_canvas()
    for cx in (EYE_L_X, EYE_R_X):
        draw_open_eye(draw, cx, EYE_Y + 6, EYE_W // 2 - 4, EYE_H // 2 - 6)
        # Sad brow — angled inward
    brow_y = EYE_Y - EYE_H // 2 - 12
    draw.line([(EYE_L_X - 28, brow_y + 10), (EYE_L_X + 28, brow_y - 4)],
              fill=OUTLINE, width=4)
    draw.line([(EYE_R_X - 28, brow_y - 4), (EYE_R_X + 28, brow_y + 10)],
              fill=OUTLINE, width=4)
    save(img, folder, "eyes_sad")


def gen_eyes_angry(folder: str) -> None:
    img, draw = new_canvas()
    for cx in (EYE_L_X, EYE_R_X):
        # Squinted eyes (narrow ellipse)
        ellipse(draw, cx, EYE_Y + 4, EYE_W // 2, EYE_H // 4,
                fill=EYE_WHITE, outline=OUTLINE, width=2)
        ellipse(draw, cx, EYE_Y + 4, PUPIL_W // 2, PUPIL_H // 4,
                fill=PUPIL_COLOR)
    # Angry angled brows
    brow_y = EYE_Y - EYE_H // 2 - 8
    draw.line([(EYE_L_X - 30, brow_y - 10), (EYE_L_X + 30, brow_y + 8)],
              fill=OUTLINE, width=5)
    draw.line([(EYE_R_X - 30, brow_y + 8), (EYE_R_X + 30, brow_y - 10)],
              fill=OUTLINE, width=5)
    save(img, folder, "eyes_angry")


def gen_eyes_surprised(folder: str) -> None:
    img, draw = new_canvas()
    for cx in (EYE_L_X, EYE_R_X):
        # Large wide-open eyes
        ellipse(draw, cx, EYE_Y, EYE_W // 2 + 8, EYE_H // 2 + 8,
                fill=EYE_WHITE, outline=OUTLINE, width=3)
        ellipse(draw, cx, EYE_Y, PUPIL_W // 2, PUPIL_H // 2, fill=EYE_IRIS)
        ellipse(draw, cx, EYE_Y, PUPIL_W // 4, PUPIL_H // 4, fill=PUPIL_COLOR)
        ellipse(draw, cx - 10, EYE_Y - 10, 7, 7, fill=(255, 255, 255, 220))
    save(img, folder, "eyes_surprised")


def gen_eyes_thinking(folder: str) -> None:
    img, draw = new_canvas()
    # Left eye: looking up-right (normal-ish)
    draw_open_eye(draw, EYE_L_X, EYE_Y, EYE_W // 2, EYE_H // 2)
    # Right eye: half-closed squint
    ellipse(draw, EYE_R_X, EYE_Y + 8, EYE_W // 2, EYE_H // 4,
            fill=EYE_WHITE, outline=OUTLINE, width=2)
    ellipse(draw, EYE_R_X, EYE_Y + 8, PUPIL_W // 2, PUPIL_H // 4,
            fill=PUPIL_COLOR)
    # Thinking brow on left
    draw.arc([EYE_L_X - 32, EYE_Y - 52, EYE_L_X + 32, EYE_Y - 22],
             start=200, end=340, fill=OUTLINE, width=4)
    save(img, folder, "eyes_thinking")


def gen_eyes_smug(folder: str) -> None:
    img, draw = new_canvas()
    # Both eyes half-closed, looking slightly down
    for cx in (EYE_L_X, EYE_R_X):
        ellipse(draw, cx, EYE_Y + 5, EYE_W // 2, EYE_H // 3,
                fill=EYE_WHITE, outline=OUTLINE, width=2)
        ellipse(draw, cx, EYE_Y + 5, PUPIL_W // 2 - 2, PUPIL_H // 3,
                fill=EYE_IRIS)
        ellipse(draw, cx, EYE_Y + 5, PUPIL_W // 4, PUPIL_H // 4,
                fill=PUPIL_COLOR)
    # Flat smug brows
    brow_y = EYE_Y - EYE_H // 2 - 6
    draw.line([(EYE_L_X - 28, brow_y), (EYE_L_X + 28, brow_y + 4)],
              fill=OUTLINE, width=4)
    draw.line([(EYE_R_X - 28, brow_y - 4), (EYE_R_X + 28, brow_y + 4)],
              fill=OUTLINE, width=4)
    save(img, folder, "eyes_smug")


# ── Mouths ───────────────────────────────────────────────────────────────────

def gen_mouth_neutral(folder: str) -> None:
    img, draw = new_canvas()
    draw.line([(CX - 40, MOUTH_Y), (CX + 40, MOUTH_Y)],
              fill=OUTLINE, width=4)
    save(img, folder, "mouth_neutral")


def gen_mouth_smile(folder: str) -> None:
    img, draw = new_canvas()
    # Smile arc
    draw.arc([CX - MOUTH_W // 2, MOUTH_Y - 25,
              CX + MOUTH_W // 2, MOUTH_Y + 35],
             start=10, end=170, fill=OUTLINE, width=5)
    save(img, folder, "mouth_smile")


def gen_mouth_sad(folder: str) -> None:
    img, draw = new_canvas()
    draw.arc([CX - MOUTH_W // 2, MOUTH_Y - 30,
              CX + MOUTH_W // 2, MOUTH_Y + 20],
             start=190, end=350, fill=OUTLINE, width=5)
    save(img, folder, "mouth_sad")


def gen_mouth_frown(folder: str) -> None:
    img, draw = new_canvas()
    draw.arc([CX - MOUTH_W // 2 + 10, MOUTH_Y - 35,
              CX + MOUTH_W // 2 - 10, MOUTH_Y + 10],
             start=190, end=350, fill=OUTLINE, width=6)
    save(img, folder, "mouth_frown")


def gen_mouth_smirk(folder: str) -> None:
    img, draw = new_canvas()
    # One side up, other flat
    draw.line([(CX - 40, MOUTH_Y), (CX + 10, MOUTH_Y)], fill=OUTLINE, width=4)
    draw.arc([CX, MOUTH_Y - 20, CX + 50, MOUTH_Y + 20],
             start=230, end=360, fill=OUTLINE, width=4)
    save(img, folder, "mouth_smirk")


def gen_mouth_open(folder: str, name: str, height: int) -> None:
    img, draw = new_canvas()
    w = MOUTH_W - 20
    # Outline
    draw.ellipse([CX - w // 2, MOUTH_Y - height // 2,
                  CX + w // 2, MOUTH_Y + height // 2],
                 outline=OUTLINE, fill=(40, 10, 20, 255), width=4)
    # Teeth strip at top
    draw.rectangle([CX - w // 2 + 6, MOUTH_Y - height // 2 + 4,
                    CX + w // 2 - 6, MOUTH_Y - height // 2 + 14],
                   fill=(245, 245, 245, 255))
    save(img, folder, name)


# ── Extras ───────────────────────────────────────────────────────────────────

def gen_blush(folder: str) -> None:
    img, draw = new_canvas()
    for cx in (BLUSH_L_X, BLUSH_R_X):
        ellipse(draw, cx, BLUSH_Y, BLUSH_W // 2, BLUSH_H // 2,
                fill=BLUSH_COLOR)
    # Soft blur for natural look
    img = img.filter(ImageFilter.GaussianBlur(radius=6))
    save(img, folder, "blush")


# ── Runner ───────────────────────────────────────────────────────────────────

def main() -> None:
    base_dir = os.path.dirname(__file__)
    base_f   = os.path.join(base_dir, "base")
    eyes_f   = os.path.join(base_dir, "eyes")
    mouth_f  = os.path.join(base_dir, "mouths")
    extra_f  = os.path.join(base_dir, "extras")

    print("Generating placeholder sprites…\n")

    print("base/")
    gen_face_base(base_f)

    print("\neyes/")
    gen_eyes_open(eyes_f)
    gen_eyes_closed(eyes_f)
    gen_eyes_happy(eyes_f)
    gen_eyes_sad(eyes_f)
    gen_eyes_angry(eyes_f)
    gen_eyes_surprised(eyes_f)
    gen_eyes_thinking(eyes_f)
    gen_eyes_smug(eyes_f)

    print("\nmouths/")
    gen_mouth_neutral(mouth_f)
    gen_mouth_smile(mouth_f)
    gen_mouth_sad(mouth_f)
    gen_mouth_frown(mouth_f)
    gen_mouth_smirk(mouth_f)
    gen_mouth_open(mouth_f, "mouth_open_1", 20)
    gen_mouth_open(mouth_f, "mouth_open_2", 35)
    gen_mouth_open(mouth_f, "mouth_open_3", 50)

    print("\nextras/")
    gen_blush(extra_f)

    print("\n✅ Done! Sprites saved in server/assets/")
    print("   Start the server with: uvicorn main:app --reload")


if __name__ == "__main__":
    main()
