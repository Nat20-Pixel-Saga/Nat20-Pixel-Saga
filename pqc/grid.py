"""Grid geometry: movement (Dijkstra over 5-ft squares) and areas of effect.

Squares are integer (x, y) pairs. Diagonal steps cost the same as straight
ones (SRD default); difficult terrain or crawling doubles a step's cost.
Area templates follow the SRD shapes approximated on the grid:

* cone   — from the caster's square towards a point; a square is inside if its
           centre is within the length and within ~26.6° (the 5e cone, whose
           width equals its length) of the aim direction.
* cube   — a cube of the given size adjacent to the caster, on the side it is
           aimed at (orthogonal or diagonal).
* sphere — every square whose centre lies within the radius of a point.
* line   — a 5-ft-wide line from the caster towards a point.
"""
from __future__ import annotations

import heapq
import math
from typing import Callable, Iterable

Square = tuple[int, int]
STEPS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def chebyshev(a: Square, b: Square) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def reachable(start: Square, budget_ft: int, passable: Callable[[Square], bool],
              step_cost: Callable[[Square], int] = lambda s: 5) -> dict[Square, tuple[int, Square | None]]:
    """Every square reachable within ``budget_ft``: {square: (cost, previous)}."""
    best: dict[Square, tuple[int, Square | None]] = {start: (0, None)}
    heap = [(0, start)]
    while heap:
        cost, sq = heapq.heappop(heap)
        if cost > best[sq][0]:
            continue
        for dx, dy in STEPS:
            nxt = (sq[0] + dx, sq[1] + dy)
            if not passable(nxt):
                continue
            c = cost + step_cost(nxt)
            if c > budget_ft:
                continue
            if nxt not in best or c < best[nxt][0] or (c == best[nxt][0] and sq < (best[nxt][1] or sq)):
                best[nxt] = (c, sq)
                heapq.heappush(heap, (c, nxt))
    return best


def path_to(tree: dict[Square, tuple[int, Square | None]], goal: Square) -> list[Square] | None:
    """Squares from the start (inclusive) to ``goal`` (inclusive)."""
    if goal not in tree:
        return None
    out = [goal]
    while tree[out[-1]][1] is not None:
        out.append(tree[out[-1]][1])
    return list(reversed(out))


def direction8(origin: Square, toward: Square) -> tuple[int, int]:
    dx, dy = toward[0] - origin[0], toward[1] - origin[1]
    if dx == 0 and dy == 0:
        return (1, 0)
    ang = math.atan2(dy, dx)
    octant = round(ang / (math.pi / 4)) % 8
    return [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)][octant]


def cone_squares(origin: Square, toward: Square, length_ft: int) -> set[Square]:
    n = length_ft // 5
    dx, dy = toward[0] - origin[0], toward[1] - origin[1]
    if dx == 0 and dy == 0:
        dx = 1
    norm = math.hypot(dx, dy)
    ux, uy = dx / norm, dy / norm
    half = math.atan(0.5) + 0.02  # width at the end equals the length
    out = set()
    for x in range(origin[0] - n, origin[0] + n + 1):
        for y in range(origin[1] - n, origin[1] + n + 1):
            vx, vy = x - origin[0], y - origin[1]
            d = math.hypot(vx, vy)
            if d == 0 or d > n + 0.75:
                continue
            if (vx * ux + vy * uy) / d >= math.cos(half):
                out.add((x, y))
    return out


def cube_squares(origin: Square, toward: Square, size_ft: int) -> set[Square]:
    n = size_ft // 5
    dx, dy = direction8(origin, toward)
    ox, oy = origin
    if dx and dy:  # diagonal: the cube touches the caster's corner
        xs = range(ox + dx, ox + dx * (n + 1), dx)
        ys = range(oy + dy, oy + dy * (n + 1), dy)
    elif dx:
        xs = range(ox + dx, ox + dx * (n + 1), dx)
        ys = range(oy - n // 2, oy - n // 2 + n)
    else:
        ys = range(oy + dy, oy + dy * (n + 1), dy)
        xs = range(ox - n // 2, ox - n // 2 + n)
    return {(x, y) for x in xs for y in ys}


def sphere_squares(center: Square, radius_ft: int) -> set[Square]:
    r = radius_ft / 5
    n = int(r) + 1
    return {(x, y) for x in range(center[0] - n, center[0] + n + 1) for y in range(center[1] - n, center[1] + n + 1)
            if math.hypot(x - center[0], y - center[1]) <= r + 0.01}


def line_squares(origin: Square, toward: Square, length_ft: int) -> set[Square]:
    n = length_ft // 5
    dx, dy = toward[0] - origin[0], toward[1] - origin[1]
    if dx == 0 and dy == 0:
        dx = 1
    norm = math.hypot(dx, dy)
    out = set()
    for i in range(1, n * 2 + 1):
        t = i / 2
        out.add((round(origin[0] + dx / norm * t), round(origin[1] + dy / norm * t)))
    out.discard(origin)
    return out


def area_squares(shape: str, size_ft: int, caster: Square, aim: Square) -> set[Square]:
    if shape == "cone":
        return cone_squares(caster, aim, size_ft)
    if shape == "cube":
        return cube_squares(caster, aim, size_ft)
    if shape == "sphere":
        return sphere_squares(aim, size_ft)
    if shape == "line":
        return line_squares(caster, aim, size_ft)
    raise ValueError(f"Unknown area shape {shape!r}")


def aims(caster: Square, points: Iterable[Square]) -> list[Square]:
    """Candidate aim points: the 8 compass directions plus given points."""
    out = [(caster[0] + dx * 3, caster[1] + dy * 3) for dx, dy in STEPS]
    for p in points:
        if p not in out and p != caster:
            out.append(p)
    return out
