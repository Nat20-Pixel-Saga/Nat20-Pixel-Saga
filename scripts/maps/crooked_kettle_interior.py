#!/usr/bin/env python3
"""Generator for assets/maps/crooked_kettle_interior.json (C1E2, C1E7).

Inside Maddy Fenn's inn, the Crooked Kettle: a wood-floored common room with
a hearth and rug on the north wall, a bar along the north-east corner with
barrels behind it, three long tables, the stairs up to the rooms, and the
front door in the south wall. Through a doorway in the east wall is the back
storeroom (barrels, crates and sacks of onions) where Rusk is kept.

Walls are one-tile props from Interior/TilesetWallSimple.png; the doorways use
the pack's end-cap pieces. Everything outside the walls is the pack's void.
"""
import json
from pathlib import Path

W, H = 25, 15
OUT = Path(__file__).resolve().parents[2] / "assets" / "maps" / "crooked_kettle_interior.json"

props = []


def add(prop, x, y, **kw):
    props.append({"prop": prop, "at": [x, y], **kw})


def room(x0, y0, x1, y1, doors_bottom=(), doors_left=(), doors_right=()):
    """A walled room; door gaps are tile coordinates along that wall."""
    add("wall_tl", x0, y0)
    add("wall_tr", x1, y0)
    add("wall_bl", x0, y1)
    add("wall_br", x1, y1)
    for x in range(x0 + 1, x1):
        add("wall_top", x, y0)
        if x in doors_bottom:
            continue
        piece = ("wall_bottom_end_r" if x + 1 in doors_bottom else
                 "wall_bottom_end_l" if x - 1 in doors_bottom else "wall_bottom")
        add(piece, x, y1)
    for side, xs, gaps in (("left", x0, doors_left), ("right", x1, doors_right)):
        for y in range(y0 + 1, y1):
            if y in gaps:
                continue
            piece = (f"wall_{side}_end_b" if y + 1 in gaps else
                     f"wall_{side}_end_t" if y - 1 in gaps else f"wall_{side}")
            add(piece, xs, y)


# Common room (interior x 1-16, y 1-13), front door at (8, 14); storeroom (x 19-23) through (17-18, 10).
room(0, 0, 17, 14, doors_bottom=(8,), doors_right=(10,))
room(18, 0, 24, 14, doors_left=(10,))

# North wall of the common room: stairs, hearth with a bench, a bookshelf for the Lamplighters' ledger.
add("stairs_up", 1, 1, label="Stairs to the rooms")
add("hearth", 3, 1, id="hearth", label="The hearth")
add("cauldron", 4, 1)
add("brazier", 2, 1, id="hearth_fire")
add("bench_long", 2, 3)
add("bookshelf", 6, 1, label="The Lamplighters' ledger shelf")
# The bar, north-east: counter along y=4, barrels and a dresser behind it.
add("table_long", 11, 4, label="The bar")
add("table_long", 14, 4)
for x in (12, 14, 16):
    add("barrel", x, 1)
add("dresser", 10, 1)
add("stool", 12, 5)
add("stool", 15, 5)
add("candle", 16, 3, id="bar_candle")
# Guest tables with chairs at their ends.
for tx, ty in ((3, 7), (3, 11), (10, 9)):
    add("table_long", tx, ty)
    add("chair", tx - 1, ty)
    add("chair", tx + 3, ty)
add("candle", 4, 7, id="table_candle")
add("vase", 16, 13)
add("vase", 1, 13)
# Storeroom: barrels, crates, sacks of onions; Rusk's corner with a candle.
for x, y in ((19, 1), (20, 1), (23, 1), (23, 2), (19, 13), (23, 13)):
    add("barrel", x, y)
for x, y in ((21, 1), (22, 1), (19, 3), (22, 12)):
    add("sack", x, y)
add("candle", 23, 6, id="store_candle")
add("dresser", 22, 9)

data = {
    "schema": "pqc/map@1", "id": "crooked_kettle_interior", "name": "The Crooked Kettle (inside)",
    "region": "lanternmarch", "biome": "interior", "size": [W, H], "base": "floor_wood", "seed": 7,
    "layers": [],
    "props": props,
    "points": {"front_door": [8, 13], "common_room": [8, 8], "hearth": [3, 4], "hearth_east": [5, 4],
               "bar": [13, 5], "behind_bar": [13, 2], "table_west": [4, 8], "table_south": [4, 10],
               "table_east": [11, 10], "stairs": [1, 2], "storeroom_door": [17, 10], "storeroom": [21, 8],
               "rusk_corner": [20, 6]},
}
# One prop per line keeps the file short and diffable.
text = json.dumps({k: v for k, v in data.items() if k != "props"}, indent=1)
props_text = ",\n".join("  " + json.dumps(p) for p in props)
OUT.write_text(text[:-2] + ',\n "props": [\n' + props_text + "\n ]\n}")
print(OUT)
