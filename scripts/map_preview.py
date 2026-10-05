#!/usr/bin/env python3
"""Render a whole map (terrain + props, y-sorted) to PNG for review.

    python scripts/map_preview.py lantern_road [out.png] [--blocked] [--points]
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def preview(map_id: str, out: Path, blocked: bool = False, points: bool = False, scale: int = 2) -> Path:
    from pqc.pipeline.resolve import blocked_squares
    from pqc.render.assets import Assets
    from pqc.render.tilemap import TileMap
    a = Assets()
    tm = TileMap.load(map_id, a)
    img = tm.ground.copy()
    for p in sorted(tm.props, key=lambda p: p.sort_y):
        img.alpha_composite(p.image, (p.x * 16, p.y * 16))
    d = ImageDraw.Draw(img)
    if blocked:
        for x, y in blocked_squares(map_id):
            d.rectangle([x * 16, y * 16, x * 16 + 15, y * 16 + 15], outline=(255, 40, 40, 200))
    if points:
        for name, (x, y) in tm.points.items():
            d.ellipse([x * 16 + 4, y * 16 + 4, x * 16 + 11, y * 16 + 11], fill=(255, 230, 0, 255))
            d.text((x * 16 + 12, y * 16), name, fill=(255, 255, 255, 255))
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    img.save(out)
    return out


if __name__ == "__main__":
    mid = sys.argv[1]
    out = Path(next((x for x in sys.argv[2:] if not x.startswith("--")), f"{mid}_preview.png"))
    print(preview(mid, out, "--blocked" in sys.argv, "--points" in sys.argv))
