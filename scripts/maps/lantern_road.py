#!/usr/bin/env python3
"""Generator for assets/maps/lantern_road.json (C1E3 "The Empty Housing").

The Lantern Road just south of Brindle Cross: the road bends south past
Lantern 37, a goblin trail of trampled dark earth leaves the road at the
lantern and runs east into the edge of Thornpike Woods. North is the village
(fence-side farm, haystacks); south, Lantern 38 in the distance.
"""
import json
from pathlib import Path

W, H = 40, 26
OUT = Path(__file__).resolve().parents[2] / "assets" / "maps" / "lantern_road.json"


def grid():
    return [["."] * W for _ in range(H)]


def rows(g):
    return ["".join(r) for r in g]


road, trail, field = grid(), grid(), grid()
for y in range(H):  # a gentle S-bend, two tiles wide
    x0 = 18 if y <= 8 else 19 if y <= 16 else 20
    for x in (x0, x0 + 1):
        road[y][x] = "D"
    if y in (8, 16):  # overlap the bends so the road stays connected
        road[y][x0 + 1 + 1] = "D"
# Goblin trail: from the foot of Lantern 37 east-south-east into the woods.
for x in range(21, W):
    yc = 13 + round((x - 22) * 0.25)          # drifts south-east into the trees
    for y in (yc, yc + 1):
        trail[y][x] = "T"
    if x > 22 and round((x - 23) * 0.25) != round((x - 22) * 0.25):
        trail[yc - 1][x] = "T"                 # widen at each step so the edge stays smooth
# A ploughed field west of the road.
for y in range(3, 9):
    for x in range(4, 13):
        field[y][x] = "F"

props = []


def add(prop, x, y, **kw):
    props.append({"prop": prop, "at": [x, y], **kw})


# Lanterns: 37 by the trail, 38 far south. (36 stands in the village, off the top edge.)
add("lantern_post", 22, 11, id="lantern_road.037", light="dead", label="Lantern 37")
add("lantern_post", 23, 23, id="lantern_road.038", light="lit", label="Lantern 38")
add("sign", 17, 4, id="milestone", label="Brindle Cross 1 mile - Fort Harrow 39 miles")
# Farm by the field.
add("haystack", 14, 4)
add("haystack", 15, 6)
add("cart", 13, 9)
add("barrel", 3, 10)
# Thornpike Woods: dense east of the road, thinning towards it.
for x, y in [(30, 0), (34, 1), (36, 4), (29, 4), (33, 7), (36, 9), (31, 19), (35, 21), (28, 22), (36, 13)]:
    add("pine_cluster", x, y)
for x, y in [(26, 2), (27, 8), (25, 17), (26, 20), (38, 11), (33, 11), (30, 10), (38, 22), (32, 24)]:
    add("tree_pine", x, y)
for x, y in [(24, 6), (28, 18), (39, 7), (34, 19)]:
    add("tree_dead", x, y)
for x, y in [(0, 0), (2, 15), (6, 19), (11, 22), (1, 23), (14, 17)]:
    add("tree_light", x, y)
for x, y in [(8, 13), (3, 2)]:
    add("tree_round", x, y)
add("boulders", 9, 16)
add("stump", 16, 20)
add("rock_brown", 25, 9)
# Tracks and signs of passage along the trail.
for x, y in [(24, 13), (28, 15), (32, 16), (36, 17)]:
    add("footprints", x, y)
add("twigs", 27, 15)
add("claw_marks", 21, 13)
add("bone", 34, 18)
# Scatter.
for x, y in [(5, 12), (12, 14), (16, 12), (23, 4), (11, 1), (7, 21), (15, 24), (24, 22)]:
    add("bush" if (x + y) % 2 else "bush2", x, y)
for x, y in [(6, 11), (10, 12), (14, 13), (22, 2), (3, 17), (9, 24), (17, 15)]:
    add("flowers" if (x * y) % 2 else "flowers2", x, y)
for x, y in [(23, 15), (17, 22), (12, 18)]:
    add("rock_small", x, y)

data = {
    "schema": "pqc/map@1", "id": "lantern_road", "name": "The Lantern Road", "region": "lanternmarch",
    "biome": "meadow", "size": [W, H], "base": "grass_base", "seed": 37,
    "layers": [{"terrain": "dirt", "rows": rows(field)}, {"terrain": "dirt", "rows": rows(road)},
               {"terrain": "dirt_dark", "rows": rows(trail)}],
    "props": props,
    "points": {"north_road": [18, 0], "milestone": [18, 5], "lantern_37": [22, 14], "lantern_37_west": [21, 12],
               "trail_start": [24, 14], "woods_edge": [30, 16], "east_exit": [39, 18], "field": [8, 10],
               "south_road": [20, 25], "lantern_38": [23, 25]},
}
OUT.write_text(json.dumps(data, indent=1))
print(OUT)
