"""The stage: world map or battle arena, actors, effects, lighting and UI.

World and battle are composed at 1x (240x135), lit, then scaled 2x to the
480x270 canvas; UI is drawn at 480x270 on top. ``Stage.render()`` returns one
RGB frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from . import lighting
from .assets import ActorSprites, Assets
from .tilemap import T, TileMap
from .ui import UI, H as CANVAS_H, W as CANVAS_W

ZOOM = 2
VIEW_W, VIEW_H = CANVAS_W // ZOOM, CANVAS_H // ZOOM  # 240 x 135


def tile_to_px(tx: float, ty: float) -> tuple[float, float]:
    """Tile coords -> pixel position of an actor's feet (bottom centre)."""
    return tx * T + T / 2, ty * T + T


@dataclass
class Actor:
    id: str
    sprites: ActorSprites
    x: float
    y: float
    facing: str = "down"
    state: str = "idle"
    anim_t: float = 0.0
    visible: bool = True
    alpha: float = 1.0
    flash_until: float = -1.0
    shake_until: float = -1.0
    dx: float = 0.0  # temporary offsets (attack lunges, hops)
    dy: float = 0.0
    emote: Image.Image | None = None
    emote_until: float = -1.0
    name: str = ""

    def image(self, t: float) -> Image.Image:
        if self.state == "down":
            img = self.sprites.frame("idle", "down", 0).transpose(Image.ROTATE_90)
            a = np.array(img).astype(np.float32)
            a[:, :, :3] = a[:, :, :3] * 0.6 + 40
            img = Image.fromarray(a.clip(0, 255).astype(np.uint8), "RGBA")
        else:
            img = self.sprites.frame(self.state, self.facing, self.anim_t)
        if t < self.flash_until and int(t * 30) % 2 == 0:
            a = np.array(img)
            a[:, :, :3] = np.where(a[:, :, 3:4] > 0, 255, a[:, :, :3])
            img = Image.fromarray(a, "RGBA")
        if self.alpha < 1.0:
            img = img.copy()
            img.putalpha(img.getchannel("A").point(lambda v: int(v * max(0.0, self.alpha))))
        return img

    def draw_xy(self, t: float) -> tuple[int, int]:
        w, h = self.sprites.size
        sx = 0
        if t < self.shake_until:
            sx = int(round(math.sin(t * 90) * 2))
        return int(round(self.x - w / 2 + self.dx + sx)), int(round(self.y - h + self.dy))


@dataclass
class Fx:
    frames: list[Image.Image]
    x: float  # centre, world px
    y: float
    t0: float
    fps: float = 14.0
    loop: bool = False
    until: float | None = None
    flip: bool = False
    front: bool = True

    def frame(self, t: float) -> Image.Image | None:
        if t < self.t0:
            return None
        i = int((t - self.t0) * self.fps)
        if self.loop:
            if self.until is not None and t > self.until:
                return None
            img = self.frames[i % len(self.frames)]
        else:
            if i >= len(self.frames):
                return None
            img = self.frames[i]
        return img.transpose(Image.FLIP_LEFT_RIGHT) if self.flip else img

    def done(self, t: float) -> bool:
        if t < self.t0:
            return False
        if self.loop:
            return self.until is not None and t > self.until
        return int((t - self.t0) * self.fps) >= len(self.frames)


@dataclass
class Projectile:
    frames: list[Image.Image]
    x0: float
    y0: float
    x1: float
    y1: float
    t0: float
    dur: float
    arc: float = 0.0

    def pos(self, t: float) -> tuple[float, float] | None:
        if t < self.t0 or t > self.t0 + self.dur:
            return None
        p = (t - self.t0) / self.dur
        return self.x0 + (self.x1 - self.x0) * p, self.y0 + (self.y1 - self.y0) * p - math.sin(p * math.pi) * self.arc

    def frame(self, t: float) -> Image.Image:
        img = self.frames[int((t - self.t0) * 16) % len(self.frames)]
        return img.transpose(Image.FLIP_LEFT_RIGHT) if self.x1 < self.x0 else img

    def done(self, t: float) -> bool:
        return t > self.t0 + self.dur


@dataclass
class Battle:
    arena: TileMap | None  # None = fight on the current world map
    party: list[str]
    enemies: list[str]
    hp: dict[str, list[int]] = field(default_factory=dict)  # id -> [hp, max]
    names: dict[str, str] = field(default_factory=dict)
    active: str | None = None
    area: list[tuple[int, int]] | None = None
    area_color: tuple[int, int, int] = (230, 70, 50)
    grid_alpha: float = 0.0
    grid_target: float = 0.16


ARENA = {
    "schema": "pqc/map@1", "id": "arena", "name": "Battle arena", "size": [15, 9], "base": "grass_base", "seed": 3,
    "layers": [{"terrain": "dirt", "rows": [
        "...............",
        "...............",
        "..DDDDDDDDDDD..",
        ".DDDDDDDDDDDDD.",
        ".DDDDDDDDDDDDD.",
        ".DDDDDDDDDDDDD.",
        "..DDDDDDDDDDD..",
        "...............",
        "...............",
    ]}],
    "props": [
        {"prop": "tree_pine", "at": [0, -1]}, {"prop": "tree_round", "at": [3, -1]}, {"prop": "tree_oak", "at": [6, -1]},
        {"prop": "tree_round", "at": [9, -1]}, {"prop": "tree_pine", "at": [12, -1]},
        {"prop": "bush", "at": [0, 7]}, {"prop": "flowers", "at": [5, 8]}, {"prop": "bush2", "at": [10, 8]},
        {"prop": "tree_round", "at": [13, 7]}, {"prop": "tree_pine", "at": [-1, 6]},
    ],
}


class Stage:
    def __init__(self, assets: Assets, fps: int = 30):
        self.a = assets
        self.fps = fps
        self.ui = UI(assets)
        self.t = 0.0
        self.map: TileMap | None = None
        self.mode = "world"
        self.actors: dict[str, Actor] = {}
        self.world_actors: dict[str, Actor] = {}
        self.fx: list[Fx] = []
        self.projectiles: list[Projectile] = []
        self.camera = [VIEW_W / 2, VIEW_H / 2]
        self.follow: str | None = None
        self.camera_tween: dict | None = None
        self.preset = "day"
        self.preset_blend = 1.0
        self.unlight: list[dict] = []
        self.fade = 0.0  # 0 clear .. 1 black
        self.wipe: dict | None = None
        self.battle: Battle | None = None
        self.audio: list[dict] = []
        self._arena_cache: TileMap | None = None

    # -------------------------------------------------------------- setup
    def set_map(self, map_id: str):
        self.map = TileMap.load(map_id, self.a)

    def spawn(self, actor_id: str, sprite: str, tx: float, ty: float, facing="down", name="") -> Actor:
        x, y = tile_to_px(tx, ty)
        a = Actor(actor_id, self.a.actor(sprite), x, y, facing, name=name or actor_id)
        self.actors[actor_id] = a
        return a

    def sfx(self, sfx_id: str, t: float | None = None, volume: float = 1.0):
        self.audio.append({"type": "sfx", "id": sfx_id, "t": self.t if t is None else t, "volume": volume})

    # ------------------------------------------------------------- battle
    def start_battle(self, party: list[dict], enemies: list[dict], on_map: bool = True):
        """On-map battles keep the world actors and place combatants at their
        engine squares (``at``). Without positions, fall back to the side-view arena."""
        on_map = on_map and self.map is not None and all("at" in c for c in party + enemies)
        b = Battle(None, [p["id"] for p in party], [e["id"] for e in enemies])
        if on_map:
            self.mode = "battle"
            for c in party + enemies:
                tx, ty = c["at"]
                if c["id"] in self.actors:
                    a = self.actors[c["id"]]
                    a.x, a.y = tile_to_px(tx, ty)
                else:
                    a = self.spawn(c["id"], c.get("sprite", c["id"]), tx, ty, name=c.get("name", c["id"]))
                a.visible, a.alpha, a.state = True, 1.0, "idle"
            for c in party + enemies:
                foes = enemies if c in party else party
                me = self.actors[c["id"]]
                if foes:
                    tgt = min(foes, key=lambda f: abs(f["at"][0] - c["at"][0]) + abs(f["at"][1] - c["at"][1]))
                    me.facing = facing_toward(c["at"], tgt["at"])
        else:
            if self._arena_cache is None:
                self._arena_cache = TileMap.from_dict(ARENA, self.a)
            b.arena = self._arena_cache
            self.world_actors = self.actors
            self.actors = {}
            self.mode = "battle"
            for i, p in enumerate(party):
                self.actors[p["id"]] = Actor(p["id"], self.a.actor(p.get("sprite", p["id"])), 186 + (i % 2) * 18,
                                             48 + i * 19, "left", name=p.get("name", p["id"]))
            n = len(enemies)
            for i, e in enumerate(enemies):
                y = 50 + i * (76 / max(1, n - 1)) if n > 1 else 76
                self.actors[e["id"]] = Actor(e["id"], self.a.actor(e["sprite"]), 56 - (i % 2) * 18, y, "right",
                                             name=e.get("name", e["id"]))
        for c in party + enemies:
            b.hp[c["id"]] = [c.get("hp", 1), c.get("max_hp", c.get("hp", 1))]
            b.names[c["id"]] = c.get("name", c["id"])
        self.battle = b

    def end_battle(self):
        if self.battle and self.battle.arena is not None:
            self.actors = self.world_actors
            self.world_actors = {}
        else:
            self.actors = {k: a for k, a in self.actors.items() if a.visible}
            for a in self.actors.values():
                a.dx = a.dy = 0
        self.camera_tween = None
        self.mode = "world"
        self.battle = None
        self.fx.clear()
        self.projectiles.clear()

    def battle_focus(self) -> tuple[float, float]:
        """Centre of the standing combatants, biased towards the active one."""
        b = self.battle
        pts = [(a.x, a.y - 8) for k, a in self.actors.items() if k in b.party + b.enemies and a.visible]
        if not pts:
            return self.camera[0], self.camera[1]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        if b.active in self.actors and (max(xs) - min(xs) > VIEW_W - 48 or max(ys) - min(ys) > VIEW_H - 56):
            a = self.actors[b.active]
            cx, cy = (cx + 2 * a.x) / 3, (cy + 2 * (a.y - 8)) / 3
        return cx, cy + 10  # leave room for the HUD at the top

    # ------------------------------------------------------------- camera
    def _camera(self) -> tuple[int, int]:
        if self.mode == "battle" and self.battle and self.battle.arena is not None:
            return 0, 4
        m = self.map
        if self.mode == "battle" and self.battle and not self.camera_tween:
            fx_, fy_ = self.battle_focus()
            if getattr(self, "_cam_frame", None) != self.t:
                self.camera = [self.camera[0] + (fx_ - self.camera[0]) * 0.08,
                               self.camera[1] + (fy_ - self.camera[1]) * 0.08]
                self._cam_frame = self.t
        if self.camera_tween:
            ct = self.camera_tween
            p = min(1.0, (self.t - ct["t0"]) / max(ct["dur"], 1e-6))
            p = p * p * (3 - 2 * p)
            self.camera = [ct["x0"] + (ct["x1"] - ct["x0"]) * p, ct["y0"] + (ct["y1"] - ct["y0"]) * p]
            if p >= 1:
                self.camera_tween = None
        elif self.follow and self.follow in self.actors:
            a = self.actors[self.follow]
            self.camera = [a.x, a.y - 8]
        cx, cy = self.camera
        mw, mh = m.pixel_size if m else (VIEW_W, VIEW_H)
        x = int(round(min(max(cx - VIEW_W / 2, 0), max(0, mw - VIEW_W))))
        y = int(round(min(max(cy - VIEW_H / 2, 0), max(0, mh - VIEW_H))))
        return x, y

    # ------------------------------------------------------------- render
    def render(self, clean: bool = False) -> Image.Image:
        t = self.t
        tm = self.battle.arena if (self.mode == "battle" and self.battle.arena is not None) else self.map
        cam_x, cam_y = self._camera()
        world = Image.new("RGBA", (VIEW_W, VIEW_H), (20, 27, 27, 255))
        if tm is not None:
            world.alpha_composite(tm.ground.crop((cam_x, cam_y, cam_x + VIEW_W, cam_y + VIEW_H)), (0, 0))
            if self.battle is not None and self.battle.arena is None:
                _draw_battle_ground(world, self, cam_x, cam_y)
            items = []
            for p in tm.props:
                if p.hidden:
                    continue
                px, py = p.x * T - cam_x, p.y * T - cam_y
                if px > VIEW_W or py > VIEW_H or px + p.image.width < 0 or py + p.image.height < 0:
                    continue
                items.append((p.sort_y, 0, p.frame(t), px, py))
            for a in self.actors.values():
                if not a.visible:
                    continue
                img = a.image(t)
                ax, ay = a.draw_xy(t)
                items.append((a.y, 1, img, ax - cam_x, ay - cam_y))
            for fx in self.fx:
                img = fx.frame(t)
                if img is not None:
                    items.append((fx.y + (1000 if fx.front else 0), 2, img, int(fx.x - img.width / 2) - cam_x,
                                  int(fx.y - img.height / 2) - cam_y))
            for pr in self.projectiles:
                pos = pr.pos(t)
                if pos:
                    img = pr.frame(t)
                    items.append((10_000, 3, img, int(pos[0] - img.width / 2) - cam_x, int(pos[1] - img.height / 2) - cam_y))
            for _, _, img, x, y in sorted(items, key=lambda it: (it[0], it[1])):
                _paste_clip(world, img, int(x), int(y))
            for a in self.actors.values():
                if a.visible and a.emote is not None and t < a.emote_until:
                    ax, ay = a.draw_xy(t)
                    _paste_clip(world, a.emote, ax - cam_x + 8, ay - cam_y - 12)
            # Lighting.
            lights, zones = [], []
            for p in tm.props:
                if p.light and p.light_spec:
                    lx, ly = p.light_center()
                    inten = lighting.flicker(t, p.id or p.prop, p.light)
                    lights.append(lighting.Light(lx - cam_x, ly - cam_y, p.light_spec.get("radius", 32), inten))
            if tm is self.map:
                for z in self.unlight:
                    pz = min(1.0, max(0.0, (t - z["t0"]) / max(z.get("grow", 0.01), 0.01)))
                    zones.append(lighting.UnlightZone(z["x"] - cam_x, z["y"] - cam_y, z["radius"] * pz, z.get("strength", 1.0)))
            arr = np.array(world.convert("RGB"))
            arr = lighting.apply(arr, self.preset, lights, zones, self.preset_blend)
            world = Image.fromarray(arr, "RGB").convert("RGBA")
        self.fx = [f for f in self.fx if not f.done(t)]
        self.projectiles = [p for p in self.projectiles if not p.done(t)]
        canvas = world.resize((CANVAS_W, CANVAS_H), Image.NEAREST)
        hud = None
        if clean:  # no dialog, dice tray or HUD (thumbnails)
            return canvas
        if self.mode == "battle" and self.battle:
            hud = [{"name": self.battle.names[i], "hp": self.battle.hp[i][0], "max_hp": self.battle.hp[i][1]}
                   for i in self.battle.party]
            _enemy_bars(canvas, self)
        self.ui.draw(canvas, t, hud)
        if self.wipe:
            _draw_wipe(canvas, self.wipe, t)
        if self.fade > 0:
            black = Image.new("RGBA", canvas.size, (0, 0, 0, int(255 * min(1.0, self.fade))))
            canvas.alpha_composite(black)
        return canvas.convert("RGB")


def facing_toward(frm, to) -> str:
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def _draw_battle_ground(world: Image.Image, st: "Stage", cam_x: int, cam_y: int):
    """Grid lines, the active creature's square and area-of-effect templates."""
    from PIL import ImageDraw
    b = st.battle
    b.grid_alpha += (b.grid_target - b.grid_alpha) * 0.15
    layer = Image.new("RGBA", world.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ga = int(255 * b.grid_alpha)
    if ga > 2:
        ox, oy = -(cam_x % T), -(cam_y % T)
        for x in range(ox, VIEW_W, T):
            d.line([(x, 0), (x, VIEW_H)], fill=(20, 27, 27, ga))
        for y in range(oy, VIEW_H, T):
            d.line([(0, y), (VIEW_W, y)], fill=(20, 27, 27, ga))
    if b.area:
        r, g, bl = b.area_color
        for (sx, sy) in b.area:
            x0, y0 = sx * T - cam_x, sy * T - cam_y
            d.rectangle((x0, y0, x0 + T - 1, y0 + T - 1), fill=(r, g, bl, 90), outline=(r, g, bl, 200))
    if b.active in st.actors and st.actors[b.active].visible and b.grid_target > 0:
        a = st.actors[b.active]
        x0 = int(a.x - T / 2) - cam_x
        y0 = int(a.y - T) - cam_y
        pulse = 160 + int(80 * abs(math.sin(st.t * 4)))
        d.rectangle((x0, y0, x0 + T - 1, y0 + T - 1), outline=(242, 201, 76, pulse))
    world.alpha_composite(layer)


def _paste_clip(dst: Image.Image, img: Image.Image, x: int, y: int):
    """Alpha-composite ``img`` at (x, y), clipped to ``dst`` on every side."""
    sx, sy = max(0, -x), max(0, -y)
    ex = min(img.width, dst.width - x)
    ey = min(img.height, dst.height - y)
    if sx >= ex or sy >= ey:
        return
    dst.alpha_composite(img.crop((sx, sy, ex, ey)), (max(0, x), max(0, y)))


def _enemy_bars(canvas: Image.Image, st: Stage):
    from PIL import ImageDraw
    d = ImageDraw.Draw(canvas)
    cx, cy = st._camera()
    for eid in st.battle.enemies:
        a = st.actors.get(eid)
        if not a or not a.visible or a.alpha <= 0.05:
            continue
        hp, mx = st.battle.hp[eid]
        ax, ay = a.draw_xy(st.t)
        x, y = (ax - cx) * ZOOM, (ay - 5 - cy) * ZOOM
        w = a.sprites.size[0] * ZOOM
        d.rectangle((x, y, x + w, y + 3), fill=(59, 54, 67, 255))
        if hp > 0:
            d.rectangle((x, y, x + int(w * hp / max(mx, 1)), y + 3), fill=(209, 75, 52, 255))


def _draw_wipe(canvas: Image.Image, wipe: dict, t: float):
    from PIL import ImageDraw
    p = (t - wipe["t0"]) / wipe["dur"]
    if p < 0 or p > 1:
        return
    cover = p * 2 if p < 0.5 else (1 - p) * 2  # close then open
    d = ImageDraw.Draw(canvas)
    bands = 9
    bh = CANVAS_H / bands
    for i in range(bands):
        y0 = i * bh
        d.rectangle((0, y0, CANVAS_W, y0 + bh * cover), fill=(0, 0, 0, 255))
