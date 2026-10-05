#!/usr/bin/env python3
"""Generator for assets/maps/fort_harrow.json (C1E10).

Fort Harrow, the tired royal garrison at the south end of the Lantern Road:
a stone curtain wall with watchtowers at the corners and an arched gate in the
south wall with a lantern beside it; inside, Captain Rook's brick command
house, two wooden barracks, a parade ground, and a training yard with straw
targets. The road runs north-south through the gate.
"""
import json
import random
from pathlib import Path

W, H = 44, 28
OUT = Path(__file__).resolve().parents[2] / "assets" / "maps" / "fort_harrow.json"
rng = random.Random(10)


def grid():
    return [["."] * W for _ in range(H)]


road, ground = grid(), grid()
open_ = set()


def paint(g, x0, y0, x1, y1, mark=True):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if 0 <= x < W and 0 <= y < H:
                g[y][x] = "T"
                if mark:
                    open_.add((x, y))


paint(road, 21, 21, 22, H - 1)          # the road up to the gate
paint(ground, 9, 10, 34, 20)            # parade ground and training yard
paint(road, 21, 8, 22, 20)              # the way from the gate to the command house

props, taken = [], set()


def add(prop, x, y, w=1, h=1, solid=True, **kw):
    props.append({"prop": prop, "at": [x, y], **kw})
    if solid:
        taken.update((x + dx, y + dy) for dx in range(w) for dy in range(h))


# Curtain wall: north and south runs of wall sections (1x2), posts down the sides.
X0, X1, YN, YS = 6, 37, 2, 21
for x in range(X0 + 2, X1):
    add("fort_wall", x, YN, 1, 2)
    if x not in (21, 22):
        add("fort_wall", x, YS, 1, 2)
add("fort_gate", 21, YS, 2, 2, solid=False, id="gate", label="The south gate")
for y in range(YN + 2, YS, 2):
    add("fort_wall_post", X0, y, 1, 2)
    add("fort_wall_post", X1, y, 1, 2)
for x, y in [(X0 - 1, YN - 1), (X1, YN - 1), (X0 - 1, YS), (X1, YS)]:
    add("watchtower", x, y, 2, 2)
add("stone_lantern", 23, 23, 1, 2, id="lantern.fort_gate", label="Gate lantern")
add("banner", 20, 23, id="banner_gate")
# Inside: command house, barracks, mess, yard.
add("house_brick", 19, 4, 4, 3, id="command_house", label="Captain Rook's command house")
add("banner", 18, 7)
add("banner", 23, 7)
add("house_wood", 9, 5, 3, 3, id="barracks_west", label="Barracks")
add("house_wood", 13, 5, 3, 3, id="barracks_west2")
add("house_wood", 29, 5, 3, 3, id="barracks_east")
add("well", 16, 12, id="well")
add("table_long", 10, 14, 3, 1, id="mess_table")
add("log_bench", 10, 16, 3, 1)
add("barrel", 8, 12)
add("barrel", 8, 13)
add("cart", 33, 8, 2, 2)
for x, y in [(28, 13), (31, 13), (34, 13)]:
    add("haystack", x, y, 1, 2)               # straw targets
for x, y in [(27, 18), (33, 18)]:
    add("barrel", x, y)
# Outside the walls: fields, trees, the road south.
margin = {(x + dx, y + dy) for (x, y) in open_ for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
inside = {(x, y) for x in range(X0, X1 + 2) for y in range(YN - 1, YS + 2)}


def fits(x, y, w, h):
    cells = [(x + dx, y + dy) for dx in range(w) for dy in range(h)]
    return not any(c in taken or c in margin or c in inside for c in cells)


spots = [(x, y) for y in range(-1, H) for x in range(-1, W)]
rng.shuffle(spots)
for x, y in spots:
    if fits(x, y, 2, 2) and rng.random() < 0.7:
        add(rng.choice(["tree_round", "tree_pine", "tree_pine", "tree_oak"]), x, y, 2, 2)
for y in range(H):
    for x in range(W):
        if fits(x, y, 1, 1) and rng.random() < 0.15:
            add(rng.choice(["bush", "bush2", "rock_small", "flowers"]), x, y, solid=False)

data = {
    "schema": "pqc/map@1", "id": "fort_harrow", "name": "Fort Harrow", "region": "lanternmarch",
    "biome": "fort", "size": [W, H], "base": "grass_base", "seed": 140,
    "layers": [{"terrain": "dirt", "rows": ["".join(r) for r in ground]},
               {"terrain": "dirt", "rows": ["".join(r) for r in road]}],
    "points": {
        "road_south": [21, 27], "gate_outside": [21, 25], "gate_inside": [21, 19], "courtyard": [21, 15],
        "command_door": [20, 8], "before_command": [21, 10], "parade_west": [14, 15], "mess": [11, 15],
        "barracks_door": [10, 9], "training_yard": [30, 16], "yard_east": [33, 16], "well_side": [17, 13],
    },
}
text = json.dumps(data, indent=1)
props_text = ",\n".join("  " + json.dumps(p) for p in props)
OUT.write_text(text[:-2] + ',\n "props": [\n' + props_text + "\n ]\n}")
print(OUT, len(props), "props")
