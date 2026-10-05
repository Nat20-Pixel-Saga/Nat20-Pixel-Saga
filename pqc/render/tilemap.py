"""Tile maps: JSON format, quarter-tile autotiling, props and lights.

Map JSON (``assets/maps/<id>.json``)::

    {
      "schema": "pqc/map@1", "id": "brindle_cross", "name": "Brindle Cross",
      "size": [40, 24],                 # tiles
      "base": "grass_base",             # fill terrain
      "layers": [{"terrain": "dirt", "rows": ["....DDD....", ...]}],
      "props": [{"prop": "house_orange", "at": [4, 2], "id": "crooked_kettle"},
                {"prop": "stone_lantern", "at": [12, 9], "id": "lantern_road.037", "light": "lit"}],
      "points": {"inn_door": [5, 5]},
      "seed": 7
    }

Layer rows use any non-space, non-"." character for "terrain here". Autotiling
builds each 16x16 tile from four 8x8 quarters chosen from the terrain's 3x3
edge block and inner corners (see manifest ``terrain._layout``).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .assets import ROOT, Assets

T = 16
H = 8  # quarter size

# Source tiles relative to a terrain block's origin.
CENTER = (1, 1)
OUTER = {"tl": (0, 0), "tr": (2, 0), "bl": (0, 2), "br": (2, 2)}
EDGE_V = {"tl": (0, 1), "bl": (0, 1), "tr": (2, 1), "br": (2, 1)}  # left / right edges
EDGE_H = {"tl": (1, 0), "tr": (1, 0), "bl": (1, 2), "br": (1, 2)}  # top / bottom edges
INNER = {"br": (5, 1), "bl": (6, 1), "tr": (5, 2), "tl": (6, 2)}  # grass in that corner
QUARTER_OFF = {"tl": (0, 0), "tr": (H, 0), "bl": (0, H), "br": (H, H)}
NEIGH = {  # (vertical neighbour, horizontal neighbour, diagonal)
    "tl": ((0, -1), (-1, 0), (-1, -1)),
    "tr": ((0, -1), (1, 0), (1, -1)),
    "bl": ((0, 1), (-1, 0), (-1, 1)),
    "br": ((0, 1), (1, 0), (1, 1)),
}


def quarter_source(q: str, vert: bool, horiz: bool, diag: bool) -> tuple[int, int]:
    """Which block tile supplies quarter ``q`` given same-terrain neighbours."""
    if vert and horiz:
        return CENTER if diag else INNER[q]
    if vert and not horiz:
        return EDGE_V[q]
    if horiz and not vert:
        return EDGE_H[q]
    return OUTER[q]


def _hash01(seed: int, x: int, y: int) -> float:
    h = hashlib.blake2b(f"{seed}:{x}:{y}".encode(), digest_size=4).digest()
    return int.from_bytes(h, "big") / 2**32


@dataclass
class PropInstance:
    prop: str
    x: int  # tile coords of top-left
    y: int
    id: str | None = None
    image: Image.Image | None = None
    light: str | None = None  # "lit" | "flicker" | "dead" | None
    light_spec: dict | None = None
    label: str | None = None
    hidden: bool = False

    @property
    def sort_y(self) -> int:
        return (self.y * T) + (self.image.height if self.image else T)

    def light_center(self) -> tuple[float, float]:
        off = (self.light_spec or {}).get("offset", [8, 8])
        return self.x * T + off[0], self.y * T + off[1]


@dataclass
class TileMap:
    id: str
    name: str
    width: int
    height: int
    base: str
    layers: list[dict]
    props: list[PropInstance]
    points: dict[str, list[int]]
    seed: int = 0
    data: dict = field(default_factory=dict)
    ground: Image.Image | None = None

    @classmethod
    def load(cls, map_id_or_path: str | Path, assets: Assets) -> "TileMap":
        p = Path(map_id_or_path)
        if not p.suffix:
            p = ROOT / "assets" / "maps" / f"{map_id_or_path}.json"
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return cls.from_dict(d, assets)

    @classmethod
    def from_dict(cls, d: dict, assets: Assets) -> "TileMap":
        w, h = d["size"]
        props = []
        for pd in d.get("props", []):
            spec = assets.prop_spec(pd["prop"])
            props.append(PropInstance(pd["prop"], pd["at"][0], pd["at"][1], pd.get("id"), assets.prop(pd["prop"]),
                                      pd.get("light", "lit" if "light" in spec else None), spec.get("light"),
                                      pd.get("label")))
        m = cls(d["id"], d.get("name", d["id"]), w, h, d.get("base", "grass_base"), d.get("layers", []), props,
                d.get("points", {}), d.get("seed", 0), d)
        for layer in m.layers:
            rows = layer["rows"]
            if len(rows) != h or any(len(r) != w for r in rows):
                raise ValueError(f"Map {m.id}: layer {layer['terrain']} must be {h} rows of {w} chars")
        m.ground = m.render_ground(assets)
        return m

    # ------------------------------------------------------------- ground
    def render_ground(self, assets: Assets) -> Image.Image:
        img = Image.new("RGBA", (self.width * T, self.height * T), (0, 0, 0, 255))
        base = assets.terrain(self.base)
        fill = [assets.tile(base["sheet"], *xy) for xy in base["fill"]]
        detail = [assets.tile(base["sheet"], *xy) for xy in base.get("detail", [])]
        rate = base.get("detail_rate", 0.0)
        for y in range(self.height):
            for x in range(self.width):
                r = _hash01(self.seed, x, y)
                tile = detail[int(r / rate * len(detail)) % len(detail)] if detail and r < rate else fill[0]
                img.alpha_composite(tile, (x * T, y * T))
        for layer in self.layers:
            spec = assets.terrain(layer["terrain"])
            ox, oy = spec["origin"]
            sheet = spec["sheet"]
            grid = [[c not in ". " for c in row] for row in layer["rows"]]
            for y in range(self.height):
                for x in range(self.width):
                    if not grid[y][x]:
                        continue
                    for q, ((vx, vy), (hx, hy), (dx, dy)) in NEIGH.items():
                        vert = self._same(grid, x + vx, y + vy)
                        horiz = self._same(grid, x + hx, y + hy)
                        diag = self._same(grid, x + dx, y + dy)
                        sx, sy = quarter_source(q, vert, horiz, diag)
                        qx, qy = QUARTER_OFF[q]
                        src = assets.tile(sheet, ox + sx, oy + sy).crop((qx, qy, qx + H, qy + H))
                        img.paste(src, (x * T + qx, y * T + qy))
        return img

    def _same(self, grid, x, y) -> bool:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return True  # terrain continues off the map edge
        return grid[y][x]

    # ------------------------------------------------------------- queries
    def blocked(self, assets: Assets) -> set[tuple[int, int]]:
        """Squares props make impassable for movement ("solid": all | base | none)."""
        out = set()
        for p in self.props:
            spec = assets.prop_spec(p.prop)
            mode = spec.get("solid", "none")
            _, _, w, h = spec["rect"]
            if mode == "all":
                out |= {(p.x + dx, p.y + dy) for dx in range(w) for dy in range(h)}
            elif mode == "base":
                out |= {(p.x + dx, p.y + h - 1) for dx in range(w)}
        return out

    def prop_by_id(self, pid: str) -> PropInstance:
        for p in self.props:
            if p.id == pid:
                return p
        raise KeyError(f"No prop {pid!r} on map {self.id}")

    def point(self, name: str) -> tuple[float, float]:
        x, y = self.points[name]
        return x, y

    @property
    def pixel_size(self) -> tuple[int, int]:
        return self.width * T, self.height * T
