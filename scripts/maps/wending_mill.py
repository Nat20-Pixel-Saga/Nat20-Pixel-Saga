#!/usr/bin/env python3
"""Generator for assets/maps/wending_mill.json and wending_mill_burning.json (C1E8, C1E9).

Wending Mill, a hamlet on the road south of Brindle Cross: a watermill whose
wheel turns in a millpond, a fenced mill yard where the road from the north
comes in, three cottages, haystacks and carts, a big barn on the east side
with open ground in front of it, and fields to the south-west.

The same layout is written twice: ``wending_mill`` (E8, the attack) and
``wending_mill_burning`` (E9: the barn is on fire and smoke hangs over the
yard). Water is terrain, so the pond is covered with invisible water_block
props to keep feet off it.
"""
import json
import random
from pathlib import Path

W, H = 44, 28
MAPS = Path(__file__).resolve().parents[2] / "assets" / "maps"


def grid():
    return [["."] * W for _ in range(H)]


def build(burning: bool) -> dict:
    rng = random.Random(8)
    road, pond, field, yard = grid(), grid(), grid(), grid()
    open_ = set()

    def paint(g, x0, y0, x1, y1, mark=True):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if 0 <= x < W and 0 <= y < H:
                    g[y][x] = "T"
                    if mark:
                        open_.add((x, y))

    # Millpond (north-west), rounded.
    for y in range(H):
        for x in range(W):
            if ((x - 15) / 4.6) ** 2 + ((y - 7) / 4.2) ** 2 <= 1 or (x, y) in {(11, 9), (12, 9), (11, 10), (12, 10)}:
                pond[y][x] = "W"            # an oval pond; the wheel squares are always water
    # Roads: north road down to the yard; lanes to the mill door, the barn and the east.
    paint(road, 21, 0, 22, 13)
    paint(road, 9, 12, 22, 13)          # lane west to the mill door
    paint(road, 9, 11, 9, 11)           # the mill door step
    paint(road, 21, 13, 32, 14)         # lane east
    paint(road, 31, 14, 32, 21)         # down to the barn front
    paint(road, 32, 13, 43, 14)         # on east, out of the hamlet
    # Mill yard and the ground in front of the barn (fight areas).
    paint(yard, 15, 16, 29, 22)
    paint(yard, 26, 22, 41, 26)
    # Fields (south-west).
    for y0 in (17, 20, 23):
        paint(field, 3, y0, 12, y0 + 1, mark=False)

    props, taken = [], set()

    def add(prop, x, y, w=1, h=1, solid=True, **kw):
        props.append({"prop": prop, "at": [x, y], **kw})
        if solid:
            taken.update((x + dx, y + dy) for dx in range(w) for dy in range(h))

    # Water is impassable.
    for y in range(H):
        for x in range(W):
            if pond[y][x] == "W":
                add("water_block", x, y)
    # The watermill: house west of the pond, wheel in the water.
    add("watermill", 8, 8, 3, 3, id="watermill", label="The watermill")
    add("barrel", 7, 11)
    add("barrel", 12, 13)
    add("cart", 13, 14, 2, 2)
    # Cottages and the barn.
    add("house_orange2", 25, 3, 4, 3, id="cottage_north")
    add("house_wood", 30, 6, 3, 3, id="cottage_east")
    add("house_beige", 36, 8, 4, 3, id="cottage_far")
    add("barn_burning" if burning else "barn", 35, 15, 4, 7, id="barn", label="The barn",
        **({"light": "flicker"} if burning else {}))
    add("well", 24, 10, id="well")
    for x, y in [(33, 16), (40, 18), (41, 20)]:
        add("haystack", x, y, 1, 2)
    add("cart", 41, 23, 2, 2)
    add("barrel", 34, 13)
    # Fences along the north side of the yard, with gaps for the road.
    for x in list(range(15, 21)) + list(range(23, 30)):
        add("fence_h", x, 15)
    for y in range(16, 22):
        add("fence_v", 14, y)
    # Fields: a scarecrow-less patch with haystacks.
    add("haystack", 5, 19, 1, 2)
    add("haystack", 10, 22, 1, 2)
    if burning:
        for x, y in [(34, 12), (37, 13), (33, 10), (39, 22)]:
            add("smoke", x, y, 2, 2, solid=False)
    # Edges: trees all round, thicker to the east and south.
    margin = {(x + dx, y + dy) for (x, y) in open_ for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    margin |= {(x, y) for y in range(H) for x in range(W) if pond[y][x] == "W" or field[y][x] == "T"}

    def fits(x, y, w, h):
        cells = [(x + dx, y + dy) for dx in range(w) for dy in range(h)]
        return not any(c in taken or c in margin for c in cells)

    spots = [(x, y) for y in range(-1, H) for x in range(-1, W)]
    rng.shuffle(spots)
    for x, y in spots:
        edge = x < 3 or x > W - 5 or y < 2 or y > H - 4
        if fits(x, y, 2, 2) and (edge or rng.random() < 0.12):
            add(rng.choice(["tree_round", "tree_round", "tree_oak", "tree_pine"]), x, y, 2, 2)
    for y in range(H):
        for x in range(W):
            if fits(x, y, 1, 1) and rng.random() < 0.05:
                add(rng.choice(["bush", "bush2", "flowers", "flowers2"]), x, y, solid=False)

    name = "Wending Mill (burning)" if burning else "Wending Mill"
    mid = "wending_mill_burning" if burning else "wending_mill"
    return {
        "schema": "pqc/map@1", "id": mid, "name": name, "region": "lanternmarch",
        "biome": "farmland", "size": [W, H], "base": "grass_base", "seed": 81,
        "layers": [{"terrain": "dirt", "rows": ["".join(r) for r in field]},
                   {"terrain": "water", "rows": ["".join(r) for r in pond]},
                   {"terrain": "dirt", "rows": ["".join(r) for r in yard]},
                   {"terrain": "dirt", "rows": ["".join(r) for r in road]}],
        "points": {
            "north_road": [21, 0], "road_bend": [21, 7], "yard_gate": [21, 14], "mill_yard": [22, 18],
            "yard_west": [17, 18], "yard_east": [27, 18], "yard_south": [22, 21], "mill_door": [9, 11],
            "millpond_bank": [16, 13], "well_side": [24, 11], "barn_front": [32, 21], "barn_yard": [33, 24],
            "barn_west": [29, 21], "barn_south": [37, 25], "cottage_north": [26, 7], "cottage_east": [31, 10],
            "east_exit": [43, 13], "south_field": [8, 19],
        },
        "props": props,
    }


for burning in (False, True):
    d = build(burning)
    text = json.dumps({k: v for k, v in d.items() if k != "props"}, indent=1)
    props_text = ",\n".join("  " + json.dumps(p) for p in d["props"])
    out = MAPS / f"{d['id']}.json"
    out.write_text(text[:-2] + ',\n "props": [\n' + props_text + "\n ]\n}")
    print(out, len(d["props"]), "props")
