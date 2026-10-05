#!/usr/bin/env python3
"""Generator for assets/maps/thornpike_woods.json (C1E4-E6).

Thornpike Woods, east of Lantern 37: dense pine forest with a goblin trail of
dark trampled earth. The trail enters from the west (the Lantern Road side)
and forks at a fallen stump:

* north to the birch clearing, open ground ringed by pale birches (E4, wolves);
* east to the goblin scout camp: a patched tent, a fire ring and a cart with
  three dead lantern-cores (E5);
* south-west to a sheltered hollow by an old Lamplighter way-marker, where the
  party camps for the night (E6).

The forest is filled procedurally (seeded) around the open areas, so canopies
never cover a path or a mark.
"""
import json
import random
from pathlib import Path

W, H = 48, 30
OUT = Path(__file__).resolve().parents[2] / "assets" / "maps" / "thornpike_woods.json"
rng = random.Random(4)


def grid():
    return [["."] * W for _ in range(H)]


trail, patch = grid(), grid()
open_ = set()


def dig(g, x, y, mark=True):
    if 0 <= x < W and 0 <= y < H:
        g[y][x] = "T"
        if mark:
            open_.add((x, y))


def path(points, width=2):
    """A trail through a list of waypoints, ``width`` tiles wide."""
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        steps = max(abs(x1 - x0), abs(y1 - y0))
        for k in range(steps + 1):
            x = x0 + round((x1 - x0) * k / steps)
            y = y0 + round((y1 - y0) * k / steps)
            for dx in range(width):
                for dy in range(width):
                    dig(trail, x + dx, y + dy)


def area(x0, y0, x1, y1, terrain=None, shave=True):
    """An open area (rounded corners); optionally paint a dirt patch."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            corner = shave and (x in (x0, x1)) and (y in (y0, y1))
            if corner:
                continue
            open_.add((x, y))
            if terrain is not None and not (x in (x0, x1) or y in (y0, y1)):
                terrain[y][x] = "P"


# Trails: west entrance -> fork; fork -> clearing (north), camp (east), hollow (south-west).
path([(0, 15), (8, 15), (16, 15)])
path([(16, 15), (16, 12)])
path([(17, 16), (24, 17), (31, 20)])
path([(15, 16), (12, 19), (10, 21)])
path([(44, 22), (47, 22)])                      # the goblins' way on, east
# Open areas.
area(6, 2, 20, 12)                               # birch clearing
area(32, 16, 45, 26, terrain=patch)              # scout camp
area(3, 20, 14, 27, terrain=patch)               # campsite hollow
area(14, 13, 19, 18)                             # the fork

props, taken = [], set()


def add(prop, x, y, w=1, h=1, solid=True, **kw):
    props.append({"prop": prop, "at": [x, y], **kw})
    if solid:
        taken.update((x + dx, y + dy) for dx in range(w) for dy in range(h))


# --- Birch clearing (E4): birches on the rim, a few rocks; open middle.
for x, y in [(6, 2), (9, 1), (13, 1), (17, 2), (19, 5), (19, 9), (6, 6), (6, 10), (11, 11), (17, 11)]:
    add("tree_light", x, y, 2, 2)
add("rock_brown", 9, 9, 2, 2)
add("bush", 14, 4, solid=False)
add("flowers2", 11, 6, solid=False)
add("bush2", 8, 4, solid=False)
# --- The fork: a fallen giant's stump.
add("stump_big", 18, 13, 2, 2)
add("twigs", 15, 14, solid=False)
# --- Scout camp (E5).
add("tent_ragged", 40, 16, 3, 3, label="Goblin tent")
add("campfire", 37, 20, 2, 2, id="camp_fire", label="Fire ring")
add("cart_cores", 43, 20, 2, 2, id="core_cart", label="Cart with three dead cores")
add("log_bench", 35, 23, 3, 1)
add("barrel", 44, 18)
add("barrel", 39, 17)
add("bone", 34, 19, solid=False)
add("skull", 41, 25, solid=False)
for x, y in [(30, 18), (31, 22), (29, 20)]:
    add("bush" if x % 2 else "bush2", x, y, solid=False)    # cover on the approach
# --- Campsite hollow (E6).
add("waymarker", 5, 21, id="waymarker", label="Old Lamplighter way-marker")
add("campfire", 8, 23, 2, 2, id="hollow_fire", label="Campfire")
add("log_bench", 10, 26, 3, 1)
add("stump", 3, 24, 2, 2)
add("flowers", 12, 21, solid=False)
add("footprints", 22, 17, solid=False)
add("footprints", 27, 18, solid=False)

# --- The forest: fill everything else, never over an open tile or its 1-tile margin.
margin = {(x + dx, y + dy) for (x, y) in open_ for dx in (-1, 0, 1) for dy in (-1, 0, 1)}


def fits(x, y, w, h, base_only_margin=False):
    cells = [(x + dx, y + dy) for dx in range(w) for dy in range(h)]
    if any(c in taken for c in cells):
        return False
    return not any(c in margin for c in cells)


spots = [(x, y) for y in range(-1, H) for x in range(-2, W)]
rng.shuffle(spots)
for x, y in spots:                       # big clusters first, in random order, so the wood looks grown
    if fits(x, y, 4, 3):
        add("pine_cluster", x, y, 4, 3)
for _ in range(3):
    for y in range(-1, H):
        for x in range(-1, W):
            if fits(x, y, 2, 2) and rng.random() < 0.55:
                add(rng.choice(["tree_pine", "tree_pine", "tree_pine", "tree_dead", "tree_round"]), x, y, 2, 2)
for y in range(H):
    for x in range(W):
        if fits(x, y, 1, 1) and rng.random() < 0.6:
            add(rng.choice(["bush", "bush2", "rock_small", "bush"]), x, y)

data = {
    "schema": "pqc/map@1", "id": "thornpike_woods", "name": "Thornpike Woods", "region": "lanternmarch",
    "biome": "forest", "size": [W, H], "base": "grass_base", "seed": 44,
    "layers": [{"terrain": "dirt_dark", "rows": ["".join(r) for r in patch]},
               {"terrain": "dirt_dark", "rows": ["".join(r) for r in trail]}],
    "points": {
        "west_entry": [0, 15], "trail_west": [6, 15], "fork": [16, 16],
        "clearing_south": [16, 11], "clearing_center": [12, 7], "clearing_west": [8, 7], "clearing_east": [16, 7],
        "clearing_north": [12, 3],
        "camp_approach": [27, 19], "camp_overlook": [30, 20], "camp_west": [34, 21], "camp_center": [38, 23],
        "camp_fire_north": [37, 19], "camp_cart": [42, 22], "camp_tent": [41, 19], "east_exit": [47, 22],
        "hollow_entry": [11, 20], "campsite": [8, 22], "campsite_east": [11, 23], "campsite_south": [8, 25],
        "waymarker_side": [6, 22], "watch_post": [13, 24],
    },
}
text = json.dumps({k: v for k, v in data.items()}, indent=1)
props_text = ",\n".join("  " + json.dumps(p) for p in props)
OUT.write_text(text[:-2] + ',\n "props": [\n' + props_text + "\n ]\n}")
print(OUT, len(props), "props")
