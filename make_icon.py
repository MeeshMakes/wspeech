#!/usr/bin/env python3
"""Generate wspeech_icon.png — a crisp speaker/sound-wave icon."""
from pathlib import Path
from PIL import Image, ImageDraw

SIZE   = 256
OUT    = Path(__file__).parent / "wspeech_icon.png"

img  = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# ── Background circle ──────────────────────────────────────────────────────────
BG_FILL   = (137, 180, 250, 255)   # #89b4fa  (Catppuccin blue)
BG_OUTER  = (202, 166, 247, 255)   # #cba6f7  (lavender ring)
draw.ellipse([4, 4, SIZE-4, SIZE-4], fill=BG_OUTER)
draw.ellipse([12, 12, SIZE-12, SIZE-12], fill=BG_FILL)

# ── Speaker body (trapezoid) ───────────────────────────────────────────────────
W = "#1e1e2e"  # dark symbol colour

cx, cy = SIZE // 2, SIZE // 2

# Speaker box
box_l, box_r = cx - 66, cx - 28
box_t, box_b = cy - 24, cy + 24
draw.rectangle([box_l, box_t, box_r, box_b], fill=W)

# Speaker cone (polygon)
cone = [
    (box_r, box_t),
    (box_r + 52, cy - 52),
    (box_r + 52, cy + 52),
    (box_r, box_b),
]
draw.polygon(cone, fill=W)

# ── Sound waves (arcs) ────────────────────────────────────────────────────────
ARC_W = 13
# wave 1
r1 = 70
draw.arc([cx + 10, cy - r1, cx + 10 + r1*2, cy + r1], -50, 50, fill=W, width=ARC_W)
# wave 2
r2 = 100
draw.arc([cx + 10, cy - r2, cx + 10 + r2*2, cy + r2], -45, 45, fill=W, width=ARC_W)
# wave 3
r3 = 130
draw.arc([cx + 10, cy - r3, cx + 10 + r3*2, cy + r3], -40, 40, fill=W, width=ARC_W)

img.save(str(OUT), "PNG")
print(f"Icon saved → {OUT}")
