#!/usr/bin/env python3
"""Generator for assets/maps/arena_pit.json: the fighting pit used by arena duels.

A sand ring fenced on four sides, a stretch of fort wall with banners and
torches behind it, braziers at the corners and standing room for a crowd.
Spectator squares are listed in ``points`` as crowd_0..n (with a facing).
"""
import json
from pathlib import Path

W, H = 21, 16
OUT = Path(__file__).resolve().parents[2] / "assets" / "maps" / "arena_pit.json"
RX0, RX1, RY0, RY1 = 4, 16, 5, 10           # the ring (inclusive)

sand = [["."] * W for _ in range(H)]
for y in range(RY0, RY1 + 1):
    for x in range(RX0, RX1 + 1):
        sand[y][x] = "S"
props = []


def add(prop, x, y, **kw):
    props.append({"prop": prop, "at": [x, y], **kw})


for x in range(1, W - 1):
    add("fort_wall", x, 0)
for x in (3, 10, 17):
    add("wall_banner", x, 0)
for x in (6, 14):
    add("wall_torch", x, 1)
for x in range(RX0, RX1 + 1):
    add("fence_h", x, RY0 - 1)
    add("fence_h", x, RY1 + 1)
for y in range(RY0, RY1 + 1):
    add("fence_v", RX0 - 1, y)
    add("fence_v", RX1 + 1, y)
for x, y in [(RX0 - 1, RY0 - 1), (RX1 + 1, RY0 - 1), (RX0 - 1, RY1 + 1), (RX1 + 1, RY1 + 1)]:
    add("brazier", x, y, light="lit")
for x, y in [(1, 13), (19, 13)]:
    add("barrel", x, y)
add("bone", 9, 9)
add("skull", 13, 6)

points = {"bear_start": [6, 7], "wolf_start": [14, 8], "center": [10, 7]}
crowd = [(x, 3, "down") for x in (4, 5, 7, 8, 9, 11, 12, 13, 15, 16)]
crowd += [(x, 12, "up") for x in (4, 6, 7, 9, 10, 11, 13, 14, 16)]
crowd += [(2, y, "right") for y in (6, 8, 9)] + [(18, y, "left") for y in (5, 7, 9)]
for i, (x, y, f) in enumerate(crowd):
    points[f"crowd_{i}"] = [x, y]
doc = {"schema": "pqc/map@1", "id": "arena_pit", "name": "The Pit", "region": "arena", "biome": "arena",
       "size": [W, H], "base": "grass_base", "seed": 20,
       "layers": [{"terrain": "sand", "rows": ["".join(r) for r in sand]}],
       "points": points, "crowd_facing": {f"crowd_{i}": f for i, (_, _, f) in enumerate(crowd)}, "props": props}
OUT.write_text(json.dumps(doc, indent=1) + "\n")
print(f"wrote {OUT} ({len(props)} props, {len(crowd)} crowd squares)")
