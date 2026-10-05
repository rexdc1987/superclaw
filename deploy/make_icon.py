#!/usr/bin/env python
"""Render deploy/assets/superclaw.ico from primitives (Pillow only).

The installer, the Start-menu shortcut and the .exe all point at this one icon,
so it is generated at build time rather than checked in as an opaque binary.
Supersampled 4x and downsampled, which keeps the three claw strokes crisp at
16x16 where a naive render turns to mush.

    python deploy/make_icon.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "assets" / "superclaw.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 4  # supersample factor

BASE_TOP = (30, 30, 46)
BASE_BOTTOM = (49, 50, 68)
RIM = (69, 71, 90)
CLAWS = [(203, 166, 247), (137, 180, 250), (148, 226, 213)]


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _claw_polygon(x0, y0, x1, y1, bend, width, steps=64):
    """Tapered, slightly curved stroke from (x0,y0) to (x1,y1).

    Width falls off as (1-t)^0.7 so the tip actually comes to a point instead of
    ending as a blunt stub.
    """
    left, right = [], []
    for i in range(steps + 1):
        t = i / steps
        cx = x0 + (x1 - x0) * t
        cy = y0 + (y1 - y0) * t + bend * math.sin(math.pi * t)
        dx, dy = (x1 - x0), (y1 - y0) + bend * math.pi * math.cos(math.pi * t)
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        half = width * (1 - t) ** 0.7 / 2
        left.append((cx + nx * half, cy + ny * half))
        right.append((cx - nx * half, cy - ny * half))
    return left + right[::-1]


def render(size: int) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-square plate with a vertical gradient.
    plate = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (1, s))
    for y in range(s):
        grad.putpixel((0, y), _lerp(BASE_TOP, BASE_BOTTOM, y / max(1, s - 1)) + (255,))
    grad = grad.resize((s, s))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.23), fill=255)
    plate.paste(grad, (0, 0), mask)
    img.alpha_composite(plate)

    inset = s * 0.035
    draw.rounded_rectangle(
        [inset, inset, s - 1 - inset, s - 1 - inset],
        radius=int(s * 0.21), outline=RIM + (255,), width=max(1, int(s * 0.011)),
    )

    # Three claws fanning up-right. Bases sit on a wide arc and the tips draw
    # back together, which keeps them visually separate even at 16x16.
    x_start = s * 0.235
    y_start = s * 0.735
    span_x = s * 0.44
    span_y = s * 0.475
    spacing = s * 0.108
    stroke = s * 0.070
    for index, color in enumerate(CLAWS):
        offset = (index - 1) * spacing
        poly = _claw_polygon(
            x_start + offset * 1.00,
            y_start - offset * 0.22,
            x_start + span_x + offset * 0.62,
            y_start - span_y + offset * 0.30,
            bend=-s * 0.042 - index * s * 0.014,
            width=stroke,
        )
        draw.polygon(poly, fill=color + (255,))

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [render(n) for n in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=[(n, n) for n in SIZES])
    print("wrote %s  (%d bytes, sizes %s)"
          % (OUT, OUT.stat().st_size, ",".join(str(n) for n in SIZES)))

    preview = OUT.with_name("superclaw-preview.png")
    sheet = Image.new("RGBA", (sum(SIZES) + 8 * len(SIZES), max(SIZES) + 16), (255, 255, 255, 0))
    x = 8
    for frame in frames:
        sheet.alpha_composite(frame, (x, 8 + (max(SIZES) - frame.width) // 2))
        x += frame.width + 8
    sheet.save(preview)
    print("wrote %s（各尺寸预览）" % preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
