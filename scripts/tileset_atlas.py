#!/usr/bin/env python3
"""Draw a tileset with a labelled 16-px grid, to pick tile coordinates for the manifest.

    python scripts/tileset_atlas.py Backgrounds/Tilesets/TilesetField.png out.png [scale]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "vendor" / "ninja-adventure"


def atlas(rel: str, out: str, scale: int = 3) -> None:
    im = Image.open(PACK / rel).convert("RGBA")
    w, h = im.size
    bg = Image.new("RGBA", im.size, (40, 40, 48, 255))
    bg.alpha_composite(im)
    big = bg.resize((w * scale, h * scale), Image.NEAREST)
    d = ImageDraw.Draw(big)
    t = 16 * scale
    for x in range(0, w // 16 + 1):
        d.line([(x * t, 0), (x * t, h * scale)], fill=(255, 0, 255, 90))
    for y in range(0, h // 16 + 1):
        d.line([(0, y * t), (w * scale, y * t)], fill=(255, 0, 255, 90))
    for x in range(w // 16):
        for y in range(h // 16):
            d.text((x * t + 2, y * t + 1), f"{x},{y}", fill=(255, 255, 0, 255))
    big.save(out)


if __name__ == "__main__":
    atlas(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3)
