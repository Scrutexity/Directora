"""Generate PWA icons from the Birkin logo.

Usage:
    python scripts/gen-icons.py [path/to/logo.png]

Outputs to static/:
    apple-touch-icon.png  180x180
    icon-192.png          192x192
    icon-512.png          512x512
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("PIL not found — run: pip install Pillow")

ROOT = Path(__file__).parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets" / "directora-logo.png"
OUT = ROOT / "static"
OUT.mkdir(exist_ok=True)

BG = (10, 15, 26, 255)  # #0A0F1A

img = Image.open(SRC).convert("RGBA")

bg = Image.new("RGBA", img.size, BG)
bg.paste(img, mask=img.split()[3])

for size, name in [(180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")]:
    canvas = Image.new("RGBA", (size, size), BG)
    logo = bg.copy()
    logo.thumbnail((size, size), Image.LANCZOS)
    offset = ((size - logo.width) // 2, (size - logo.height) // 2)
    canvas.paste(logo, offset)
    canvas.convert("RGB").save(OUT / name, "PNG")
    print(f"✅  {name} ({size}x{size})")

print(f"\nIcons written to {OUT}/")
