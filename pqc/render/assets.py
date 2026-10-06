"""Asset library: everything the renderer draws or plays, by logical id.

All art comes from ``assets/manifest.json``. Pack paths are resolved against
``pack_root`` (the CC0 Ninja Adventure pack fetched by scripts/fetch_assets.sh).
Images are cached; recolours swap exact palette colours.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFont

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "assets" / "manifest.json"

DIRECTIONS = ("down", "up", "left", "right")


class AssetError(RuntimeError):
    pass


def hex_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def recolor(img: Image.Image, mapping: dict[str, str] | None) -> Image.Image:
    if not mapping:
        return img
    a = np.array(img.convert("RGBA"))
    out = a.copy()
    for src, dst in mapping.items():
        s, d = hex_rgb(src), hex_rgb(dst)
        mask = (a[:, :, 0] == s[0]) & (a[:, :, 1] == s[1]) & (a[:, :, 2] == s[2])
        out[mask, :3] = d
    return Image.fromarray(out, "RGBA")


def tint(img: Image.Image, color: str, strength: float = 0.65) -> Image.Image:
    """Tint a sprite towards a colour, keeping its alpha and shading."""
    a = np.array(img.convert("RGBA")).astype(np.float32)
    c = np.array(hex_rgb(color), dtype=np.float32)
    lum = (a[:, :, :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32))[..., None] / 255.0
    a[:, :, :3] = a[:, :, :3] * (1 - strength) + (c * (0.35 + 0.9 * lum)) * strength
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


INK = (20, 27, 27)   # Ninja Adventure's outline colour


def outline(img: Image.Image) -> Image.Image:
    """Give flat art (e.g. Kenney's) the pack's 1-px dark outline: transparent pixels next to the sprite
    become ink, and so do sprite pixels on the crop's border (where there's no room outside)."""
    a = np.array(img.convert("RGBA"))
    op = a[:, :, 3] >= 128
    pad = np.pad(op, 1, constant_values=False)
    ring = ~op & (pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:])
    border = np.zeros_like(op)
    border[[0, -1], :] = op[[0, -1], :]
    border[:, [0, -1]] |= op[:, [0, -1]]
    a[ring | border] = (*INK, 255)
    return Image.fromarray(a, "RGBA")


@dataclass
class ActorSprites:
    """Frames for one actor. ``walk[dir]`` has 4 frames; other poses one per dir."""

    id: str
    walk: dict[str, list[Image.Image]]
    idle: dict[str, Image.Image]
    attack: dict[str, Image.Image]
    jump: dict[str, Image.Image]
    poses: dict[str, Image.Image]  # dead, item, special1, special2
    faceset: Image.Image | None
    voice_pitch: int = 260
    size: tuple[int, int] = (16, 16)
    meta: dict = field(default_factory=dict)

    def frame(self, state: str, direction: str, t: float) -> Image.Image:
        if state == "walk":
            frames = self.walk[direction]
            return frames[int(t * 8) % len(frames)]
        if state == "attack":
            return self.attack[direction]
        if state == "jump":
            return self.jump[direction]
        if state in self.poses:
            return self.poses[state]
        # idle: gentle two-frame breathing using walk frames 0 and 2 slowly
        return self.idle[direction]


class Assets:
    def __init__(self, manifest_path: Path = MANIFEST, root: Path = ROOT):
        self.root = root
        with open(manifest_path, encoding="utf-8") as f:
            self.manifest = json.load(f)
        self.pack = root / self.manifest["pack_root"]
        if not (self.pack / "LICENSE.txt").exists():
            raise AssetError(f"Asset pack missing at {self.pack}. Run scripts/fetch_assets.sh")
        self._img: dict[str, Image.Image] = {}
        self._actors: dict[str, ActorSprites] = {}
        self._fx: dict[str, list[Image.Image]] = {}
        self._props: dict[str, Image.Image] = {}
        self._prop_frames: dict[str, tuple[list[Image.Image], float]] = {}
        self._art_index: dict[str, dict] = {}

    # ------------------------------------------------------------ paths
    def path(self, rel: str) -> Path:
        if rel.startswith(("vendor/", "assets/")):
            return self.root / rel
        return self.pack / rel

    def image(self, rel: str) -> Image.Image:
        if rel not in self._img:
            p = self.path(rel)
            if not p.exists():
                raise AssetError(f"Missing image {p}")
            self._img[rel] = Image.open(p).convert("RGBA")
        return self._img[rel]

    # ----------------------------------------------------------- actors
    def actor(self, actor_id: str) -> ActorSprites:
        if actor_id in self._actors:
            return self._actors[actor_id]
        try:
            spec = self.manifest["actors"][actor_id]
        except KeyError as exc:
            raise AssetError(f"Unknown actor {actor_id!r}") from exc
        rc = spec.get("recolor")
        base = spec["src"]
        face = None
        if self.path(f"{base}/Faceset.png").exists():
            face = recolor(self.image(f"{base}/Faceset.png"), rc)
        if spec["type"] == "character":
            sheet = recolor(self.image(f"{base}/SpriteSheet.png"), rc)
            rows = sheet.height // 16

            def cell(col, row):
                row = min(row, rows - 1)
                return sheet.crop((col * 16, row * 16, col * 16 + 16, row * 16 + 16))

            walk = {d: [cell(i, r) for r in range(min(4, rows))] for i, d in enumerate(DIRECTIONS)}
            idle = {d: walk[d][0] for d in DIRECTIONS}
            attack = {d: cell(i, 4) if rows > 4 else walk[d][1] for i, d in enumerate(DIRECTIONS)}
            jump = {d: cell(i, 5) if rows > 5 else walk[d][2] for i, d in enumerate(DIRECTIONS)}
            poses = {}
            if rows > 6:
                poses = {"dead": cell(0, 6), "item": cell(1, 6), "special1": cell(2, 6), "special2": cell(3, 6)}
            else:
                poses = {"dead": walk["down"][0], "item": walk["down"][0], "special1": walk["down"][0],
                         "special2": walk["down"][0]}
            size = (16, 16)
        elif spec["type"] == "monster":
            sheet = recolor(self.image(f"{base}/{spec['sheet']}"), rc)
            fw, fh = sheet.width // 4, sheet.height // 4
            walk = {d: [sheet.crop((i * fw, r * fh, i * fw + fw, r * fh + fh)) for r in range(4)]
                    for i, d in enumerate(DIRECTIONS)}
            idle = {d: walk[d][0] for d in DIRECTIONS}
            attack = {d: walk[d][1] for d in DIRECTIONS}
            jump = {d: walk[d][2] for d in DIRECTIONS}
            poses = {"dead": walk["down"][0], "item": walk["down"][0], "special1": walk["down"][1],
                     "special2": walk["down"][2]}
            size = (fw, fh)
        else:
            raise AssetError(f"Unsupported actor type {spec['type']!r}")
        sprites = ActorSprites(actor_id, walk, idle, attack, jump, poses, face,
                               voice_pitch=spec.get("voice", {}).get("pitch", 260), size=size, meta=spec)
        self._actors[actor_id] = sprites
        return sprites

    # ----------------------------------------------------------- props
    def _crop(self, sheet: str | None, rect: list[int], outlined: bool) -> Image.Image:
        x, y, w, h = rect
        if sheet is None:                              # an animation-only prop (see prop_frames)
            return Image.new("RGBA", (w * 16, h * 16), (0, 0, 0, 0))
        img = self.image(sheet).crop((x * 16, y * 16, (x + w) * 16, (y + h) * 16))
        return outline(img) if outlined else img

    def prop(self, prop_id: str) -> Image.Image:
        """The prop's still image. "outline": true adds the pack's dark outline (for flat third-party art)."""
        if prop_id not in self._props:
            spec = self.manifest["props"].get(prop_id)
            if spec is None:
                raise AssetError(f"Unknown prop {prop_id!r}")
            self._props[prop_id] = self._crop(spec.get("sheet"), spec["rect"], spec.get("outline", False))
        return self._props[prop_id]

    def prop_frames(self, prop_id: str) -> tuple[list[Image.Image], float] | None:
        """Animation frames and fps for props with an "anim" block, else None. Two kinds, combinable:
        "rects": other cells of the same sheet to cycle through (a two-frame torch), and
        "fx" + "at" (or several such "layers"): an effect strip drawn over the still image at pixel
        offsets (flames on a barn roof), each placement "phase" frames out of step with the one before
        so they don't flicker in unison. Overlays are clipped to the prop's rect."""
        spec = self.manifest["props"][prop_id]
        anim = spec.get("anim")
        if not anim:
            return None
        if prop_id not in self._prop_frames:
            outlined = spec.get("outline", False)
            bases = [self._crop(spec.get("sheet"), r, outlined) for r in anim.get("rects", [])] or [self.prop(prop_id)]
            layers = anim.get("layers") or ([{"fx": anim["fx"], "at": anim.get("at", [[0, 0]]),
                                              "phase": anim.get("phase", 3)}] if anim.get("fx") else [])
            strips = [self.fx(layer["fx"]) for layer in layers]
            n = len(bases)
            for st in strips:
                n = math.lcm(n, len(st))
            frames = []
            for k in range(n):
                img = bases[k % len(bases)].copy()
                for layer, st in zip(layers, strips):
                    for i, (ox, oy) in enumerate(layer["at"]):
                        f = st[(k + i * layer.get("phase", 3)) % len(st)]
                        over = Image.new("RGBA", img.size, (0, 0, 0, 0))
                        over.paste(f, (ox, oy))
                        img.alpha_composite(over)
                frames.append(img)
            self._prop_frames[prop_id] = (frames, float(anim.get("fps", 8)))
        return self._prop_frames[prop_id]

    def prop_spec(self, prop_id: str) -> dict:
        return self.manifest["props"][prop_id]

    # ----------------------------------------------------------- terrain
    def tile(self, sheet: str, tx: int, ty: int) -> Image.Image:
        return self.image(sheet).crop((tx * 16, ty * 16, tx * 16 + 16, ty * 16 + 16))

    def terrain(self, name: str) -> dict:
        return self.manifest["terrain"][name]

    # --------------------------------------------------------------- fx
    def fx(self, fx_id: str, color: str | None = None) -> list[Image.Image]:
        key = f"{fx_id}|{color}"
        if key not in self._fx:
            spec = self.manifest["fx"].get(fx_id)
            if spec is None:
                raise AssetError(f"Unknown fx {fx_id!r}")
            strip = self.image(spec["src"])
            fw = spec["frame_w"]
            frames = [strip.crop((i * fw, 0, i * fw + fw, strip.height)) for i in range(strip.width // fw)]
            if color:
                frames = [tint(f, color) for f in frames]
            self._fx[key] = frames
        return self._fx[key]

    def spell_fx(self, spell_id: str) -> dict:
        sf = self.manifest["spell_fx"]
        return sf.get(spell_id, sf["_default"])

    # ------------------------------------------------------------- art
    def art(self, art_id: str) -> Image.Image:
        """Close-up and card art by "<kind>:<id>", e.g. "item:lantern_lit", "creature:goblin",
        "spell:fire_bolt". Kinds map to sheets in the manifest's "art"; each sheet has a JSON index."""
        kind, _, key = art_id.partition(":")
        base = self.manifest.get("art", {}).get(kind)
        if base is None:
            raise AssetError(f"Unknown art kind {kind!r}")
        if kind not in self._art_index:
            self._art_index[kind] = json.loads(self.path(base + ".json").read_text())
        idx = self._art_index[kind]
        if key not in idx["ids"]:
            raise AssetError(f"No {kind} art {key!r}")
        i, c, cols = idx["ids"].index(key), idx["cell"], idx["cols"]
        return self.image(base + ".png").crop(((i % cols) * c, (i // cols) * c, (i % cols + 1) * c, (i // cols + 1) * c))

    def art_ids(self, kind: str) -> list[str]:
        base = self.manifest.get("art", {}).get(kind)
        return json.loads(self.path(base + ".json").read_text())["ids"] if base else []

    def spell_icon(self, spell_id: str) -> Image.Image:
        """The spell's painted icon (64 px), or the generic one."""
        return self.art(f"spell:{spell_id}" if spell_id in self.art_ids("spell") else "spell:_default")

    # ------------------------------------------------------------ audio
    def music_path(self, music_id: str) -> Path:
        return self.path(self.manifest["music"][music_id])

    def sfx_path(self, sfx_id: str) -> Path:
        return self.path(self.manifest["sfx"][sfx_id])

    # -------------------------------------------------------------- ui
    def font(self, name: str) -> ImageFont.FreeTypeFont:
        return _font(str(self.path(self.manifest["fonts"][name]["file"])), self.manifest["fonts"][name]["size"])

    def font_at(self, name: str, size: int) -> ImageFont.FreeTypeFont:
        return _font(str(self.path(self.manifest["fonts"][name]["file"])), size)

    def ui(self, name: str) -> Image.Image:
        return self.image(self.manifest["ui"][name])

    def emote(self, name: str) -> Image.Image:
        n = self.manifest["ui"]["emotes"].get(name, name)
        return self.image(f"Ui/Emote/emote{n}.png")

    # ------------------------------------------------------------ audit
    def missing_files(self) -> list[str]:
        """Every manifest path that doesn't exist on disk."""
        m = self.manifest
        paths = []
        for a in m["actors"].values():
            paths.append(f"{a['src']}/Faceset.png")
            paths.append(f"{a['src']}/{a.get('sheet', 'SpriteSheet.png')}")
        paths += [t["sheet"] for k, t in m["terrain"].items() if not k.startswith("_")]
        paths += [p["sheet"] for p in m["props"].values() if p.get("sheet")]
        paths += [f["src"] for f in m["fx"].values()]
        paths += list(m["music"].values()) + list(m["sfx"].values())
        paths += [f["file"] for f in m["fonts"].values()]
        paths += [m["ui"]["dialog_face"], m["ui"]["dialog_plain"], m["ui"]["arrow"]]
        paths += [b + ext for b in m.get("art", {}).values() for ext in (".png", ".json")]
        return [p for p in paths if not self.path(p).exists()]


@lru_cache(maxsize=None)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)
