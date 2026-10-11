"""The Pit: arena episodes as broadcast timelines (16:9, and the state the 9:16 Shorts read).

An episode is a list of *segments* (see ``pqc.arena.season``): duels and team
matches (best of N), "how many" ramps (one fighter against ever bigger hordes),
and free-for-all rumbles. ``episode_cues`` turns the simulated result into
timeline cues: the stock battle cues of the renderer (moves, attacks with the
logged dice, faints) wrapped in the show's own cues (cards, captions, the live
win chance, the crowd).

The overlay is drawn on top of every frame by ``install()``; ``tick()`` advances
the eased values once per frame whether or not the frame is drawn, so a Short
can start rendering in the middle of an episode and see exactly what the
episode shows at that moment.
"""
from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw

from .. import data
from ..dice import DiceSpec
from ..render import stage as stage_mod
from ..render import timeline as tl
from ..render.director import battle_cues
from ..render.stage import Stage
from ..render.ui import GOLD, GREY, UI, WHITE, H, W, draw_text

A_COL = (236, 142, 58, 255)
B_COL = (92, 164, 236, 255)
FFA_COLS = [(236, 142, 58, 255), (92, 164, 236, 255), (134, 199, 92, 255), (230, 110, 170, 255),
            (242, 214, 92, 255), (168, 128, 236, 255), (92, 214, 206, 255), (226, 84, 72, 255)]
DARK = (20, 27, 27, 235)
PANEL = (20, 27, 27, 242)
ROW_A = (42, 42, 50, 255)
ROW_B = (29, 34, 37, 255)
RED = (226, 84, 72, 255)
GREEN = (134, 199, 92, 255)
SUB_RED = (204, 32, 32, 255)
CROWD_SPRITES = ["villager_a", "soldier", "villager_b", "miller", "villager_c", "soldier_b", "soldier_c"]
SHOW = "THE PIT"


# =================================================================== text
# Tiny5 is drawn on an 8-pixel grid, so it is only crisp at multiples of 8: every
# overlay uses it at 8, 16, 24, 32 or 48. The digits have to be unmistakable.
_FONTS: dict = {}


def font(st_or_assets, size: int):
    a = getattr(st_or_assets, "a", st_or_assets)
    k = (id(a), size)
    if k not in _FONTS:
        _FONTS[k] = a.font_at("small", size)
    return _FONTS[k]


@lru_cache(maxsize=8192)
def _text_img(text: str, f, fill: tuple, shadow: tuple | None) -> Image.Image:
    w = int(f.getlength(text)) + 3
    img = Image.new("RGBA", (max(1, w), f.size * 2 + 2), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    dd.fontmode = "1"
    if shadow:
        dd.text((1, 1), text, font=f, fill=shadow)
    dd.text((0, 0), text, font=f, fill=fill)
    return img


def put(d, xy, text, f, fill, shadow=(20, 27, 27, 255)):
    """draw_text, through a cache of rendered strings (FreeType is the slowest part of a frame)."""
    if not text:
        return
    img = _text_img(str(text), f, tuple(fill), tuple(shadow) if shadow else None)
    d._image.paste(img, (int(xy[0]), int(xy[1])), img)


def center(d, x, y, text, f, fill, shadow=(20, 27, 27, 255)):
    put(d, (int(x - f.getlength(text) / 2), int(y)), text, f, fill, shadow)


def right(d, x, y, text, f, fill):
    put(d, (int(x - f.getlength(text)), int(y)), text, f, fill)


def left(d, x, y, text, f, fill):
    put(d, (int(x), int(y)), text, f, fill)


def fit(st, text: str, width: int, sizes=(48, 32, 24, 16, 8)):
    for s in sizes:
        f = font(st, s)
        if f.getlength(text) <= width:
            return f
    return font(st, sizes[-1])


def ease(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


def slam(st, d, x, y, text, size: int, fill, age: float, dur: float = 0.18, grow: float = 0.8):
    """Text that lands: drawn oversized, settling to ``size`` over ``dur`` seconds."""
    s = 1.0 + grow * (1 - ease(age / dur))
    px = size if s < 1.02 else max(8, int(size * s / 8) * 8)
    center(d, x, y - (px - size) / 2, text, font(st, px), fill)


def pct(p: float) -> str:
    v = p * 100
    if 0 < v < 1:
        return "<1%"
    if 99 < v < 100:
        return ">99%"
    return f"{int(round(v))}%"


# ================================================================ sprites
def face(st, sprite: str, scale: int = 1, flip: bool = False) -> Image.Image:
    return _face(st.a, sprite, scale, flip)


@lru_cache(maxsize=512)
def _face(a, sprite: str, scale: int, flip: bool) -> Image.Image:
    class _S:
        pass
    st = _S()
    st.a = a
    f = st.a.actor(sprite).faceset
    if f is None:
        f = _icon(a, sprite, 2)
    if flip:
        f = f.transpose(Image.FLIP_LEFT_RIGHT)
    return f.resize((f.width * scale, f.height * scale), Image.NEAREST) if scale != 1 else f


def icon(st, sprite: str, scale: int = 1) -> Image.Image:
    """A creature's standing frame, trimmed (for rosters and scoreboards)."""
    return _icon(st.a, sprite, scale)


@lru_cache(maxsize=512)
def _icon(a, sprite: str, scale: int) -> Image.Image:
    sp = a.actor(sprite)
    img = sp.frame("idle", "down", 0)
    bb = img.getbbox()
    if bb:
        img = img.crop(bb)
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST) if scale != 1 else img


def subscribe_button(st, scale: int = 1, pressed: bool = False) -> Image.Image:
    """Pixel "SUBSCRIBE" button with a bell, drawn in code."""
    return _button(st.a, scale, pressed)


@lru_cache(maxsize=16)
def _button(a, scale: int, pressed: bool) -> Image.Image:
    f = font(a, 16 if scale == 1 else 32)
    tw = int(f.getlength("SUBSCRIBE"))
    pad = 8 * scale
    bw, bh = tw + pad * 2 + 18 * scale, 22 * scale
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = (150, 150, 150, 255) if pressed else SUB_RED
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=4 * scale, fill=col, outline=(20, 27, 27, 255), width=scale)
    put(d, (pad, (bh - f.size) // 2 + scale), "SUBSCRIBE" if not pressed else "SUBSCRIBED", f, WHITE, None)
    # bell
    bx, by, s = bw - 16 * scale, 5 * scale, scale
    d.rectangle((bx + 2 * s, by + 2 * s, bx + 8 * s, by + 9 * s), fill=WHITE)
    d.rectangle((bx + 3 * s, by, bx + 7 * s, by + 2 * s), fill=WHITE)
    d.rectangle((bx, by + 9 * s, bx + 10 * s, by + 10 * s), fill=WHITE)
    d.rectangle((bx + 4 * s, by + 11 * s, bx + 6 * s, by + 12 * s), fill=WHITE)
    return img


def odds_bar(d, x0, y0, x1, y1, p: float, ca=A_COL, cb=B_COL):
    mid = int(round(x0 + (x1 - x0) * p))
    d.rectangle((x0 - 1, y0 - 1, x1 + 1, y1 + 1), fill=(20, 27, 27, 255))
    d.rectangle((x0, y0, mid, y1), fill=ca)
    d.rectangle((mid, y0, x1, y1), fill=cb)
    d.rectangle((mid - 1, y0 - 2, mid, y1 + 2), fill=WHITE)


def hp_color(frac: float):
    return GREEN if frac > 0.5 else GOLD if frac > 0.25 else RED


# ================================================================== state
def tick(st: Stage) -> None:
    """Advance the overlay's eased values by one frame (called for every frame, drawn or not)."""
    sh = getattr(st, "show", None)
    if not sh:
        return
    t, dt = st.t, 1.0 / st.fps
    for k, v in sh["odds_target"].items():
        cur = sh["odds_shown"].get(k, v)
        sh["odds_shown"][k] = cur + (v - cur) * min(1.0, dt * 6)
    for fid, f in sh["fighters"].items():
        if st.battle and fid in st.battle.hp:
            f["hp"] = st.battle.hp[fid][0]
        f["hp_shown"] += (f["hp"] - f["hp_shown"]) * min(1.0, dt * 14)
        if f["hp_ghost"] > f["hp_shown"]:
            f["hp_ghost"] = max(f["hp_shown"], f["hp_ghost"] - f["max_hp"] * dt * 0.45)
        else:
            f["hp_ghost"] = f["hp_shown"]
    for i, cid in enumerate(sh["crowd"]):
        a = st.actors.get(cid)
        if not a:
            continue
        if t < sh["cheer_until"]:
            a.dy = -abs(math.sin(t * 11 + i * 1.7)) * 3
        else:
            ph = (t * 0.8 + i * 0.61) % 3.7
            a.dy = -math.sin(ph / 0.28 * math.pi) * 2 if ph < 0.28 else 0
    # Where a 9:16 crop of this frame should be centred, and how far in (eased; canvas pixels).
    tx, ty, spread = focus(st)
    k = min(1.0, dt * 3)
    sh["crop_x"] = tx if sh.get("crop_x") is None else sh["crop_x"] + (tx - sh["crop_x"]) * k
    sh["crop_y"] = ty if sh.get("crop_y") is None else sh["crop_y"] + (ty - sh["crop_y"]) * k
    zt = 2.0 if spread < 110 else 1.0
    sh["zoom"] = zt if sh.get("zoom") is None else sh["zoom"] + (zt - sh["zoom"]) * min(1.0, dt * 2.5)


def focus(st: Stage) -> tuple[float, float, float]:
    """Centre of the standing fighters in canvas pixels (biased to whoever acts when they are spread
    out), and how far apart they are."""
    cam_x, cam_y = st._camera()
    sh = st.show
    pts = []
    if st.battle:
        act = st.battle.active
        for fid in sh["fighters"]:
            a = st.actors.get(fid)
            if a and a.visible and a.alpha > 0.3:
                pts.append(((a.x - cam_x) * 2, (a.y - 8 - cam_y) * 2, fid == act))
    if not pts:
        return W / 2, H / 2, 999.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    spread = max(max(xs) - min(xs), max(ys) - min(ys))
    if max(xs) - min(xs) > 230:
        act = [p for p in pts if p[2]]
        if act:
            cx = (cx + 2 * act[0][0]) / 3
    return cx, cy, spread


def setup_state(st: Stage, c: dict) -> None:
    prev = getattr(st, "show", None) or {}
    st.show = {
        "layout": prev.get("layout", "wide"), "card": None, "caption": None, "cta": None, "hud": False,
        "odds_target": dict(c.get("odds", {})), "odds_shown": dict(c.get("odds", {})),
        "shake_until": -1, "flash_until": -1, "cheer_until": -1, "crop_x": prev.get("crop_x"),
        "crowd": c.get("crowd", prev.get("crowd", [])), "round": 1, "label": "", "score": [0, 0],
        "fighters": {}, **c["static"],
    }
    for fid, f in st.show["fighters_static"].items():
        st.show["fighters"][fid] = {**f, "hp": f["max_hp"], "hp_shown": f["max_hp"], "hp_ghost": f["max_hp"],
                                    "col": tuple(f["col"]), "out": False}
    for s in st.show.get("sides", {}).values():
        s["col"] = tuple(s["col"])


def reset_fighters(st: Stage) -> None:
    for f in st.show["fighters"].values():
        f.update(hp=f["max_hp"], hp_shown=f["max_hp"], hp_ghost=f["max_hp"], out=False)


# ================================================================== HUD (16:9)
def _side_panel(d, layer, st, side: str):
    sh = st.show
    s = sh["sides"][side]
    is_a = side == "a"
    x0 = 4 if is_a else W - 116
    members = [sh["fighters"][m] for m in s["members"]]
    d.rounded_rectangle((x0, 4, x0 + 112, 48), radius=3, fill=DARK, outline=s["col"])
    layer.alpha_composite(face(st, s["sprite"], flip=not is_a), (x0 + 2 if is_a else x0 + 72, 6))
    tx = x0 + 42 if is_a else x0 + 4
    left(d, tx, 6, s["label"].upper()[:12], font(st, 8), s["col"])
    if len(members) == 1:
        f = members[0]
        frac, gfrac = max(0.0, f["hp_shown"] / f["max_hp"]), max(0.0, f["hp_ghost"] / f["max_hp"])
        d.rectangle((tx, 17, tx + 64, 24), fill=(59, 54, 67, 255))
        for fr, c in ((gfrac, WHITE), (frac, hp_color(frac))):
            if fr > 0:
                w = max(1, int(64 * fr))
                d.rectangle((tx, 17, tx + w, 24) if is_a else (tx + 64 - w, 17, tx + 64, 24), fill=c)
        left(d, tx, 28, f"{int(round(f['hp_shown']))}", font(st, 16), WHITE)
        left(d, tx + 24, 35, f"/{f['max_hp']}", font(st, 8), GREY)
    else:
        standing = sum(1 for f in members if f["hp"] > 0)
        left(d, tx, 15, f"{standing}", font(st, 16), WHITE)
        left(d, tx + 18, 22, f"/ {len(members)} LEFT", font(st, 8), GREY)
        for i, f in enumerate(members):
            px, py = tx + (i % 6) * 11, 33 + (i // 6) * 6
            d.rectangle((px, py, px + 9, py + 3), fill=(59, 54, 67, 255))
            frac = max(0.0, f["hp_shown"] / f["max_hp"])
            if frac > 0:
                d.rectangle((px, py, px + max(1, int(9 * frac)), py + 3), fill=hp_color(frac))
    if sh.get("need"):
        for i in range(sh["need"]):          # bouts won
            px = (tx + 64 - (sh["need"] - i) * 9) if is_a else (tx + 46 + i * 9)
            won = i < sh["score"][0 if is_a else 1]
            d.rectangle((px, 38, px + 6, 44), fill=GOLD if won else (59, 54, 67, 255), outline=(20, 27, 27, 255))


def _sprite_bars(d, st):
    """Small HP bars over every combatant, in its side's colour (fights with more than two creatures)."""
    cam_x, cam_y = st._camera()
    for fid, f in st.show["fighters"].items():
        a = st.actors.get(fid)
        if not a or not a.visible or a.alpha < 0.3 or f["hp"] <= 0:
            continue
        ax, ay = a.draw_xy(st.t)
        x, y = (ax - cam_x) * 2 + a.sprites.size[0] - 10, (ay - cam_y) * 2 - 6
        d.rectangle((x - 1, y - 1, x + 21, y + 3), fill=(20, 27, 27, 255))
        frac = max(0.0, f["hp_shown"] / f["max_hp"])
        d.rectangle((x, y, x + max(1, int(20 * frac)), y + 2), fill=f["col"])


def _scoreboard(d, layer, st):
    """Free-for-all: every fighter with HP and live chance to win."""
    sh = st.show
    rows = sorted(sh["fighters"].values(), key=lambda f: f["order"])
    x0, y0 = 4, 4
    h = 14 + 14 * len(rows)
    d.rounded_rectangle((x0, y0, x0 + 122, y0 + h), radius=3, fill=(20, 27, 27, 215), outline=GOLD)
    left(d, x0 + 5, y0 + 3, sh.get("board_title", "LAST ONE STANDING"), font(st, 8), GOLD)
    for i, f in enumerate(rows):
        y = y0 + 14 + i * 14
        out = f["hp"] <= 0
        ic = icon(st, f["sprite"])
        if ic.height > 12:
            ic = ic.resize((max(1, ic.width * 12 // ic.height), 12), Image.NEAREST)
        if out:
            ic = ic.convert("LA").convert("RGBA")
        layer.alpha_composite(ic, (x0 + 5 + (12 - min(12, ic.width)) // 2, y))
        left(d, x0 + 20, y + 2, f["short"][:10].upper(), font(st, 8), GREY if out else f["col"])
        if out:
            d.line((x0 + 20, y + 6, x0 + 76, y + 6), fill=RED, width=1)
            right(d, x0 + 118, y + 2, "OUT", font(st, 8), RED)
            continue
        frac = max(0.0, f["hp_shown"] / f["max_hp"])
        d.rectangle((x0 + 70, y + 4, x0 + 90, y + 7), fill=(59, 54, 67, 255))
        d.rectangle((x0 + 70, y + 4, x0 + 70 + max(1, int(20 * frac)), y + 7), fill=hp_color(frac))
        right(d, x0 + 118, y + 2, pct(sh["odds_shown"].get(f["team"], 0)), font(st, 8), WHITE)


def _bottom_bar(d, st):
    sh = st.show
    d.rectangle((0, H - 28, W, H), fill=(20, 27, 27, 225))
    if sh["fmt"] == "rumble":
        teams = sorted(sh["fighters"].values(), key=lambda f: -sh["odds_shown"].get(f["team"], 0))
        x0, x1 = 58, W - 58
        x = x0
        d.rectangle((x0 - 1, H - 15, x1 + 1, H - 5), fill=(20, 27, 27, 255))
        for f in teams:
            w = (x1 - x0) * sh["odds_shown"].get(f["team"], 0)
            if w >= 1:
                d.rectangle((int(x), H - 14, int(x + w), H - 6), fill=f["col"])
            x += w
        center(d, W / 2, H - 26, "CHANCE TO BE THE LAST ONE STANDING", font(st, 8), GREY)
        lead = teams[0]
        left(d, 6, H - 20, pct(sh["odds_shown"].get(lead["team"], 0)), font(st, 16), lead["col"])
        right(d, W - 6, H - 20, lead["short"][:10].upper(), font(st, 8), lead["col"])
        return
    p = sh["odds_shown"].get("a", 0.5)
    sa, sb = sh["sides"]["a"], sh["sides"]["b"]
    odds_bar(d, 58, H - 14, W - 58, H - 6, p, sa["col"], sb["col"])
    center(d, W / 2, H - 26, sh.get("bar_title", "CHANCE TO WIN THE MATCH"), font(st, 8), GREY)
    left(d, 8, H - 20, pct(p), font(st, 16), sa["col"])
    right(d, W - 8, H - 20, pct(1 - p), font(st, 16), sb["col"])


def _caption(d, st, y_base=H - 52, width=W - 24):
    cap = st.show.get("caption")
    if not cap or not (cap["t0"] <= st.t <= cap["t0"] + cap["dur"]):
        return
    age = st.t - cap["t0"]
    f = font(st, 16)
    if f.getlength(cap["text"]) > width:
        f = font(st, 8)
    tw = f.getlength(cap["text"])
    y = y_base + int((1 - ease(age / 0.15)) * 8)
    d.rounded_rectangle((W / 2 - tw / 2 - 8, y, W / 2 + tw / 2 + 8, y + 19), radius=3, fill=DARK,
                        outline=cap.get("col", GOLD))
    center(d, W / 2, y + (2 if f.size == 16 else 6), cap["text"], f, cap.get("col", WHITE))


def _cta(layer, st):
    """Lower-third subscribe prompt: slides in, the button gets pressed, slides out."""
    c = st.show.get("cta")
    if not c or not (c["t0"] <= st.t <= c["t0"] + c["dur"]):
        return
    age, dur = st.t - c["t0"], c["dur"]
    slide = ease(age / 0.3) if age < dur - 0.3 else ease((dur - age) / 0.3)
    btn = subscribe_button(st, pressed=age > dur * 0.55)
    d = ImageDraw.Draw(layer)
    f = font(st, 8)
    text = c.get("text", "CALL YOUR WINNER IN THE COMMENTS")
    w = btn.width + 12 + int(f.getlength(text)) + 12
    x = int(W - (w + 8) * slide)
    y = H - 82
    d.rounded_rectangle((x, y, x + w, y + 30), radius=4, fill=DARK, outline=WHITE)
    layer.alpha_composite(btn, (x + 4, y + 4))
    left(d, x + btn.width + 12, y + 11, text, f, WHITE)


def draw_fight_hud(layer: Image.Image, st: Stage):
    sh = st.show
    d = ImageDraw.Draw(layer)
    if sh["fmt"] == "rumble":
        _sprite_bars(d, st)
        _scoreboard(d, layer, st)
    else:
        if len(sh["fighters"]) > 2:
            _sprite_bars(d, st)
        _side_panel(d, layer, st, "a")
        _side_panel(d, layer, st, "b")
    if not st.ui.dice:                        # round marker where the dice tray lands
        text = sh["label"] + (f"  -  ROUND {sh['round']}" if sh["label"] else f"ROUND {sh['round']}")
        tw = font(st, 8).getlength(text)
        x = W / 2 if sh["fmt"] != "rumble" else W / 2 + 60
        d.rounded_rectangle((x - tw / 2 - 8, 5, x + tw / 2 + 8, 19), radius=3, fill=DARK)
        center(d, x, 8, text, font(st, 8), GOLD)
    _bottom_bar(d, st)
    _caption(d, st)
    _cta(layer, st)


# ================================================================== cards (16:9)
def _panel(d, box, col=GOLD):
    d.rounded_rectangle(box, radius=5, fill=PANEL, outline=col)


def _rows(d, st, rows, y0: int, step: int, age: float, t0: float, gap: float, cols, x0=38, x1=W - 38, split=52):
    """Stat rows revealed one at a time: value, label, value (row[3] = 'a'/'b' marks the better one)."""
    for i, row in enumerate(rows):
        if age < t0 + i * gap:
            break
        label, va, vb = row[0], row[1], row[2]
        best = row[3] if len(row) > 3 else None
        y = y0 + i * step
        fresh = age - (t0 + i * gap) < 0.12
        d.rectangle((x0, y, x1, y + step - 2), fill=ROW_A if i % 2 == 0 else ROW_B)
        mid = (x0 + x1) / 2
        center(d, mid, y + (step - 10) // 2, label, font(st, 8), GREY)
        fa = font(st, 16) if font(st, 16).getlength(str(va)) < mid - split - x0 - 4 else font(st, 8)
        fb = font(st, 16) if font(st, 16).getlength(str(vb)) < x1 - mid - split - 4 else font(st, 8)
        ca = WHITE if fresh else GOLD if best == "a" else cols[0]
        cb = WHITE if fresh else GOLD if best == "b" else cols[1]
        right(d, mid - split, y + (step - fa.size) // 2 + (1 if fa.size == 8 else 0), str(va), fa, ca)
        left(d, mid + split, y + (step - fb.size) // 2 + (1 if fb.size == 8 else 0), str(vb), fb, cb)


def card_hook(layer, st, c, age, dur):
    d = ImageDraw.Draw(layer)
    d.rectangle((0, 46, W, 224), fill=(20, 27, 27, 220))
    top, mid, bottom = c["lines"]
    ca, cb = tuple(c.get("col_top", A_COL)), tuple(c.get("col_bottom", B_COL))
    ft = fit(st, top, W - 24)
    fb = fit(st, bottom, W - 24)
    ax = -300 + (W / 2 + 300) * ease(age / 0.3)
    bx = W + 300 - (W / 2 + 300) * ease((age - 0.25) / 0.3)
    center(d, ax, 52 + (48 - ft.size) // 2, top, ft, ca)
    if age > 0.25:
        center(d, bx, 140 + (48 - fb.size) // 2, bottom, fb, cb)
    if age > 0.6:
        slam(st, d, W / 2, 108, mid, 24, GOLD, age - 0.6, grow=1.0)
    if age > 1.0:
        txt = c.get("tag", "REAL DICE  /  NO REROLLS")
        n = int((age - 1.0) * 45)
        center(d, W / 2, 198, txt if n >= len(txt) else txt[:n], font(st, 16), WHITE)


def card_tape(layer, st, c, age, dur):
    d = ImageDraw.Draw(layer)
    _panel(d, (28, 10, W - 28, H - 10))
    center(d, W / 2, 14, c.get("title", "TALE OF THE TAPE"), font(st, 16), GOLD)
    layer.alpha_composite(face(st, c["a"]["sprite"], 2), (52, 34))
    layer.alpha_composite(face(st, c["b"]["sprite"], 2, flip=True), (W - 52 - 76, 34))
    center(d, 90, 114, c["a"]["name"].upper(), font(st, 8), tuple(c["a"]["col"]))
    center(d, W - 90, 114, c["b"]["name"].upper(), font(st, 8), tuple(c["b"]["col"]))
    center(d, W / 2, 54, c.get("vs", "VS"), font(st, 32), WHITE)
    if c.get("sub"):
        center(d, W / 2, 92, c["sub"], font(st, 8), GREY)
    _rows(d, st, c["rows"], 128, 20, age, 0.6, 0.45, (WHITE, WHITE))


def card_field(layer, st, c, age, dur):
    """Rumble roster: every fighter with HP and AC."""
    d = ImageDraw.Draw(layer)
    _panel(d, (20, 10, W - 20, H - 10))
    center(d, W / 2, 14, c.get("title", "THE FIELD"), font(st, 16), GOLD)
    n = len(c["fighters"])
    cols = 4 if n > 4 else n
    cw = (W - 56) // cols
    for i, f in enumerate(c["fighters"]):
        if age < 0.3 + i * 0.35:
            break
        cx = 28 + (i % cols) * cw + cw // 2
        cy = 38 + (i // cols) * 106
        fc = face(st, f["sprite"])
        layer.alpha_composite(fc, (cx - fc.width // 2, cy))
        center(d, cx, cy + 42, f["name"].upper()[:14], font(st, 8), tuple(f["col"]))
        center(d, cx, cy + 54, f"HP {f['hp']}  AC {f['ac']}", font(st, 8), WHITE)
        center(d, cx, cy + 66, f["note"][:18], font(st, 8), GREY)


def card_odds(layer, st, c, age, dur):
    d = ImageDraw.Draw(layer)
    _panel(d, (28, 30, W - 28, H - 30))
    center(d, W / 2, 38, c["title"], fit(st, c["title"], W - 72, (16, 8)), GOLD)
    kind = c.get("kind_card", "two")
    if kind == "two":
        p = 0.5 + (c["p"] - 0.5) * ease((age - 0.5) / 1.3)
        ca, cb = tuple(c["a"]["col"]), tuple(c["b"]["col"])
        left(d, 70, 68, c["a"]["name"].upper(), font(st, 8), ca)
        right(d, W - 70, 68, c["b"]["name"].upper(), font(st, 8), cb)
        odds_bar(d, 70, 80, W - 70, 100, p, ca, cb)
        left(d, 70, 106, pct(p), font(st, 32), ca)
        right(d, W - 70, 106, pct(1 - p), font(st, 32), cb)
        if age > 1.9 and c.get("line"):
            center(d, W / 2, 150, c["line"], fit(st, c["line"], W - 72, (16, 8)), WHITE)
    elif kind == "ramp":                       # "how many": the star's chance for each horde size
        rows = c["rows"]
        y0 = 64
        for i, (label, p) in enumerate(rows):
            if age < 0.4 + i * 0.3:
                break
            y = y0 + i * 18
            right(d, 150, y, label, font(st, 16), WHITE)
            grow = ease((age - 0.4 - i * 0.3) / 0.6)
            d.rectangle((158, y + 2, 158 + 200, y + 14), fill=(59, 54, 67, 255))
            d.rectangle((158, y + 2, 158 + int(200 * p * grow), y + 14), fill=tuple(c["col"]))
            left(d, 366, y, pct(p * grow) if grow < 1 else pct(p), font(st, 16), WHITE)
    elif kind == "field":                      # rumble: everyone's chance
        rows = sorted(c["rows"], key=lambda r: -r[1])
        for i, (name, p, col) in enumerate(rows):
            if age < 0.3 + i * 0.2:
                break
            y = 62 + i * 17
            right(d, 170, y + 1, name.upper()[:16], font(st, 8), tuple(col))
            grow = ease((age - 0.3 - i * 0.2) / 0.6)
            d.rectangle((178, y, 178 + 180, y + 10), fill=(59, 54, 67, 255))
            d.rectangle((178, y, 178 + int(180 * p * grow), y + 10), fill=tuple(col))
            left(d, 366, y - 3, pct(p), font(st, 16), WHITE)
    if age > c.get("cta_at", 3.0) and c.get("cta"):
        center(d, W / 2, H - 58, c["cta"], fit(st, c["cta"], W - 72, (16, 8)), GOLD)


def card_bout(layer, st, c, age, dur):
    d = ImageDraw.Draw(layer)
    d.rectangle((0, 86, W, 184), fill=(20, 27, 27, 220))
    f = fit(st, c["title"], W - 24, (48, 32, 24))
    slam(st, d, W / 2, 90 + (48 - f.size) // 2, c["title"], f.size, GOLD, age)
    if c.get("sub"):
        center(d, W / 2, 148, c["sub"], fit(st, c["sub"], W - 24, (16, 8)), WHITE)
    if c.get("sub2"):
        center(d, W / 2, 168, c["sub2"], font(st, 8), GREY)


def card_ko(layer, st, c, age, dur):
    d = ImageDraw.Draw(layer)
    d.rectangle((0, 72, W, 196), fill=(20, 27, 27, 225))
    slam(st, d, W / 2, 74, c.get("big", "K.O."), 48, tuple(c.get("big_col", RED)), age, dur=0.15, grow=1.2)
    if age > 0.45:
        center(d, W / 2, 134, c["line"], fit(st, c["line"], W - 24, (16, 8)), tuple(c["col"]))
    if age > 0.8 and c.get("sub"):
        center(d, W / 2, 164, c["sub"], fit(st, c["sub"], W - 24, (16, 8)), WHITE)


def card_result(layer, st, c, age, dur):
    d = ImageDraw.Draw(layer)
    col = tuple(c["col"])
    _panel(d, (28, 8, W - 28, H - 8), col)
    layer.alpha_composite(face(st, c["sprite"], 2), (48, 20))
    left(d, 140, 18, c.get("kicker", "WINNER"), font(st, 16), GOLD)
    f = fit(st, c["name"].upper(), W - 180, (32, 24, 16))
    left(d, 140, 34 + (32 - f.size) // 2, c["name"].upper(), f, col)
    left(d, 140, 74, c["line"], fit(st, c["line"], W - 180, (16, 8)), WHITE)
    rows = c.get("rows", [])
    if c.get("row_kind") == "list":
        for i, (label, val, vcol) in enumerate(rows):
            if age < 0.8 + i * 0.3:
                break
            y = 106 + i * 16
            d.rectangle((38, y, W - 38, y + 14), fill=ROW_A if i % 2 == 0 else ROW_B)
            left(d, 46, y + 3, label, font(st, 8), GREY)
            right(d, W - 46, y + 3, val, font(st, 8), tuple(vcol))
    else:
        if c.get("names"):
            right(d, W / 2 - 52, 94, c["names"][0].upper()[:14], font(st, 8), tuple(c["cols"][0]))
            left(d, W / 2 + 52, 94, c["names"][1].upper()[:14], font(st, 8), tuple(c["cols"][1]))
        _rows(d, st, rows, 106, 20, age, 1.0, 0.4, (tuple(c["cols"][0]), tuple(c["cols"][1])))
    if c.get("stamp") and age > 2.6:
        s = 1.0 + 0.6 * (1 - ease((age - 2.6) / 0.2))
        f = font(st, 16 if s < 1.1 else 24)
        tw = f.getlength(c["stamp"])
        y = H - 46
        d.rounded_rectangle((W / 2 - tw / 2 - 10, y - 4, W / 2 + tw / 2 + 10, y + 20), radius=3,
                            fill=(60, 44, 12, 255), outline=GOLD)
        center(d, W / 2, y, c["stamp"], f, GOLD)
    elif c.get("foot") and age > 2.6:
        center(d, W / 2, H - 40, c["foot"], fit(st, c["foot"], W - 72, (16, 8)), GOLD)


def _slot(d, layer, st, x, y, slot, w=98):
    filled = slot.get("sprite")
    d.rounded_rectangle((x, y, x + w, y + 64), radius=3, fill=ROW_A if filled else ROW_B,
                        outline=GOLD if filled else (59, 54, 67, 255))
    if filled:
        fc = face(st, slot["sprite"])
        layer.alpha_composite(fc, (x + (w - fc.width) // 2, y + 4))
        center(d, x + w / 2, y + 44, slot["name"].upper()[:12], font(st, 8), WHITE)
        center(d, x + w / 2, y + 54, slot["note"][:16], font(st, 8), GOLD)
    else:
        center(d, x + w / 2, y + 10, "?", font(st, 32), (90, 86, 110, 255))
        center(d, x + w / 2, y + 44, slot["name"][:16], font(st, 8), GREY)
        center(d, x + w / 2, y + 54, slot["note"][:16], font(st, 8), GREY)


def card_road(layer, st, c, age, dur):
    """Road to the Crown: the four places, paired as they meet in the semifinals."""
    d = ImageDraw.Draw(layer)
    _panel(d, (16, 10, W - 16, H - 10))
    center(d, W / 2, 16, c.get("title", "ROAD TO THE BRONZE CROWN"), font(st, 16), GOLD)
    center(d, W / 2, 36, c.get("sub", "FOUR PLACES. ONE CROWN."), font(st, 8), GREY)
    (a0, a1), (b0, b1) = c["pairs"]
    order = [a0, a1, b0, b1]
    xs = [24, 126, 256, 358]
    for k, idx in enumerate(order):
        if age < 0.3 + k * 0.25:
            break
        _slot(d, layer, st, xs[k], 64, c["slots"][idx])
    if age > 1.3:
        for k, x in enumerate((24, 256)):
            center(d, x + 100, 82, "VS", font(st, 16), WHITE)
            center(d, x + 100, 52, f"SEMIFINAL {k + 1}", font(st, 8), GOLD)
        center(d, W / 2, 140, c.get("pair_line", ""), font(st, 8), WHITE)
    if age > 2.0 and c.get("line"):
        center(d, W / 2, 158, c["line"], fit(st, c["line"], W - 56, (16, 8)), GOLD)
    if age > 2.6:
        btn = subscribe_button(st, pressed=age > 4.0)
        layer.alpha_composite(btn, (W // 2 - btn.width // 2, 186))
        center(d, W / 2, 216, c.get("cta", "SUBSCRIBE TO FOLLOW THE ROAD TO THE CROWN"), font(st, 8), WHITE)


def card_next(layer, st, c, age, dur):
    """The end screen: next fight, and two empty frames where YouTube's end-screen elements go."""
    d = ImageDraw.Draw(layer)
    _panel(d, (12, 8, W - 12, H - 8))
    center(d, W / 2, 14, c.get("kicker", "NEXT IN THE PIT"), font(st, 8), GREY)
    f = fit(st, c["title"], W - 40, (32, 24, 16))
    center(d, W / 2, 26 + (32 - f.size) // 2, c["title"], f, GOLD)
    center(d, W / 2, 62, c["when"], font(st, 16), WHITE)
    # End-screen placeholders: a video tile (left) and the subscribe circle (right).
    bx, by, bw, bh = 40, 96, 210, 118
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=4, outline=(90, 86, 110, 255), width=1)
    if c.get("a_sprite"):
        fa = face(st, c["a_sprite"])
        layer.alpha_composite(fa, (bx + bw // 2 - fa.width - 10, by + 30))
        if c.get("b_sprite"):
            fb = face(st, c["b_sprite"], flip=True)
            layer.alpha_composite(fb, (bx + bw // 2 + 10, by + 30))
            center(d, bx + bw / 2, by + 42, "VS", font(st, 8), WHITE)
    center(d, bx + bw / 2, by + bh - 20, c.get("tile", "WATCH THE LAST FIGHT"), font(st, 8), GREY)
    cx, cy, r = W - 120, by + bh // 2, 48
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(90, 86, 110, 255), width=1)
    btn = subscribe_button(st, pressed=age > 2.5 and int(age * 2) % 6 == 0)
    layer.alpha_composite(btn, (cx - btn.width // 2, cy - btn.height // 2))
    center(d, W / 2, H - 44, c.get("foot", "NEW FIGHTS EVERY WEDNESDAY AND SATURDAY"), font(st, 8), WHITE)
    if c.get("foot2"):
        center(d, W / 2, H - 30, c["foot2"], font(st, 8), GOLD)


def card_bracket(layer, st, c, age, dur):
    """Four-fighter bracket with each fighter's chance to take the Crown."""
    d = ImageDraw.Draw(layer)
    _panel(d, (16, 10, W - 16, H - 10))
    center(d, W / 2, 16, c.get("title", "THE BRONZE CROWN"), font(st, 16), GOLD)
    if c.get("sub"):
        center(d, W / 2, 36, c["sub"], font(st, 8), GREY)
    ents = c["entrants"]                       # 4 entrants in bracket order
    ys = [56, 104, 150, 198]
    for i, e in enumerate(ents):
        if age < 0.3 + i * 0.2:
            break
        y = ys[i]
        out = e.get("out")
        d.rounded_rectangle((28, y, 168, y + 36), radius=3, fill=ROW_A, outline=GOLD if not out else (59, 54, 67, 255))
        ic = icon(st, e["sprite"], 2)
        if ic.height > 32:
            ic = icon(st, e["sprite"])
        if out:
            ic = ic.convert("LA").convert("RGBA")
        layer.alpha_composite(ic, (34, y + 18 - ic.height // 2))
        left(d, 72, y + 6, e["name"].upper()[:12], font(st, 8), GREY if out else WHITE)
        left(d, 72, y + 18, ("OUT" if out else pct(e["p"]) + " TO WIN"), font(st, 8), RED if out else GOLD)
    if age > 1.2:
        # Semifinal lines and winners.
        for k, (i, j) in enumerate([(0, 1), (2, 3)]):
            y1, y2 = ys[i] + 18, ys[j] + 18
            d.line((168, y1, 196, y1), fill=GREY)
            d.line((168, y2, 196, y2), fill=GREY)
            d.line((196, y1, 196, y2), fill=GREY)
            ym = (y1 + y2) // 2
            d.line((196, ym, 232, ym), fill=GREY)
            sf = c["semis"][k]
            d.rounded_rectangle((232, ym - 18, 352, ym + 18), radius=3, fill=ROW_A if sf else ROW_B,
                                outline=GOLD if sf else (59, 54, 67, 255))
            if sf:
                ic = icon(st, sf["sprite"])
                layer.alpha_composite(ic, (238, ym - ic.height // 2))
                left(d, 262, ym - 4, sf["name"].upper()[:11], font(st, 8), WHITE)
            else:
                center(d, 292, ym - 4, c["semi_labels"][k], font(st, 8), GREY)
        ya, yb = (ys[0] + ys[1]) // 2 + 18, (ys[2] + ys[3]) // 2 + 18
        d.line((352, ya, 372, ya), fill=GREY)
        d.line((352, yb, 372, yb), fill=GREY)
        d.line((372, ya, 372, yb), fill=GREY)
        ym = (ya + yb) // 2
        champ = c.get("champion")
        d.rounded_rectangle((376, ym - 22, W - 22, ym + 22), radius=3, fill=(60, 44, 12, 255) if champ else ROW_B,
                            outline=GOLD)
        if champ:
            ic = icon(st, champ["sprite"])
            layer.alpha_composite(ic, (382, ym - ic.height // 2))
            left(d, 404, ym - 10, "CHAMPION", font(st, 8), GOLD)
            left(d, 404, ym + 2, champ["name"].upper()[:9], font(st, 8), WHITE)
        else:
            center(d, (376 + W - 22) / 2, ym - 4, c.get("final_label", "FINAL"), font(st, 8), GOLD)
    if age > 2.0 and c.get("line"):
        center(d, W / 2, H - 30, c["line"], fit(st, c["line"], W - 56, (16, 8)), GOLD)


def card_crown(layer, st, c, age, dur):
    """The champion's coronation."""
    d = ImageDraw.Draw(layer)
    _panel(d, (16, 8, W - 16, H - 8), GOLD)
    center(d, W / 2, 12, c.get("kicker", "SEASON 1 CHAMPION"), font(st, 16), GOLD)
    fc = face(st, c["sprite"], 3)
    drop = int((1 - ease(age / 0.5)) * -40)
    layer.alpha_composite(fc, (W // 2 - fc.width // 2, 54))
    # A pixel crown landing on the portrait.
    cx, cy = W // 2, 56 + drop
    crown = [(-24, 0), (-24, -18), (-12, -8), (0, -22), (12, -8), (24, -18), (24, 0)]
    d.polygon([(cx + x, cy + y) for x, y in crown], fill=GOLD, outline=(150, 104, 40, 255))
    for x in (-24, 0, 24):
        d.rectangle((cx + x - 2, cy - (18 if x else 22) - 3, cx + x + 2, cy - (18 if x else 22) + 1), fill=RED)
    f = fit(st, c["name"].upper(), W - 40, (32, 24, 16))
    slam(st, d, W / 2, 172 + (32 - f.size) // 2, c["name"].upper(), f.size, GOLD, max(0, age - 0.6))
    if age > 1.2:
        center(d, W / 2, 210, c["line"], fit(st, c["line"], W - 48, (16, 8)), WHITE)
    if age > 2.4 and c.get("foot"):
        center(d, W / 2, 234, c["foot"], fit(st, c["foot"], W - 48, (16, 8)), GREY)


def card_text(layer, st, c, age, dur):
    """Plain announcement: a title and up to five lines."""
    d = ImageDraw.Draw(layer)
    _panel(d, (24, 20, W - 24, H - 20), tuple(c.get("col", GOLD)))
    f = fit(st, c["title"], W - 64, (32, 24, 16))
    center(d, W / 2, 34, c["title"], f, tuple(c.get("col", GOLD)))
    for i, line in enumerate(c.get("lines", [])):
        if age < 0.5 + i * 0.4:
            break
        center(d, W / 2, 84 + i * 24, line, fit(st, line, W - 64, (16, 8)), WHITE if i else GOLD)
    if c.get("button") and age > 1.5:
        btn = subscribe_button(st, pressed=age > 3.0)
        layer.alpha_composite(btn, (W // 2 - btn.width // 2, H - 64))


CARDS = {"hook": card_hook, "tape": card_tape, "field": card_field, "odds": card_odds, "bout": card_bout,
         "ko": card_ko, "result": card_result, "road": card_road, "next": card_next, "bracket": card_bracket,
         "crown": card_crown, "text": card_text}
FIGHT_OVER = ("bout", "ko")                    # cards drawn over the fight HUD


# ================================================================= overlay
def overlay(st: Stage, frame: Image.Image) -> Image.Image:
    sh = st.show
    t = st.t
    img = frame.convert("RGBA")
    if t < sh["shake_until"]:
        k = (sh["shake_until"] - t) / 0.3
        img = ImageChops.offset(img, int(round(math.sin(t * 95) * 4 * k)), int(round(math.cos(t * 80) * 3 * k)))
    if t < sh["flash_until"]:
        img.alpha_composite(Image.new("RGBA", img.size, (255, 255, 255, int(150 * (sh["flash_until"] - t) / 0.14))))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    card = sh.get("card")
    if card and card["t0"] <= t < card["t0"] + card["dur"]:
        if card["kind"] in FIGHT_OVER and sh["hud"]:
            draw_fight_hud(layer, st)
        CARDS[card["kind"]](layer, st, card["c"], t - card["t0"], card["dur"])
    elif sh["hud"]:
        draw_fight_hud(layer, st)
    if st.fade > 0:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * (1 - min(1.0, st.fade)))))
    img.alpha_composite(layer)
    return img.convert("RGB")


_INSTALLED = {}


def install():
    """Hook the show into the renderer (this process only)."""
    if _INSTALLED:
        return
    orig_render = Stage.render
    orig_dice = UI.draw_dice
    orig_popups = UI.draw_popups

    def render(self, clean: bool = False):
        sh = getattr(self, "show", None)
        frame = orig_render(self, clean)
        if not sh or clean or sh.get("layout") == "tall":
            return frame
        return overlay(self, frame)

    def draw_dice(self, canvas, t):
        sh = getattr(self, "_stage_show", None)
        if sh and sh.get("layout") == "tall":
            self.dice = [dd for dd in self.dice if t <= dd["t0"] + dd["dur"]]
            return
        orig_dice(self, canvas, t)

    Stage.render = render
    UI.draw_dice = draw_dice
    from ..render import ui as ui_mod
    ui_mod.draw_text = lambda d, xy, text, f, fill, shadow=None: put(d, xy, text, f, fill, shadow)
    UI.draw_popups = orig_popups
    stage_mod._enemy_bars = lambda canvas, st: None      # the show HUD replaces these
    UI.draw_hud = lambda self, canvas, t, members: None
    UI.draw_banner = lambda self, canvas, t: None
    tl.TASKS.update(TASKS)
    _INSTALLED["on"] = True


class ShowRunner(tl.Runner):
    """Runner that ticks the show once per frame, drawn or not. ``layout`` "tall" leaves the
    overlay out (the 9:16 composer draws its own); ``render_from`` skips drawing before that time."""

    layout = "wide"
    render_from = 0.0

    def _frame(self, render: bool):
        st = self.stage
        if getattr(st, "show", None):
            st.show["layout"] = self.layout
            st.ui._stage_show = st.show
            tick(st)
        if render and st.t + 1e-6 < self.render_from:
            render = False
        return super()._frame(render)


# ==================================================================== cues
class ShowSetup(tl.Task):
    def start(self, st):
        super().start(st)
        setup_state(st, self.cue)
        st.ui.f_text = st.ui.f_pop = st.ui.f_num = font(st, 16)
        st.ui.f_small = font(st, 8)


class ShowCard(tl.Task):
    def start(self, st):
        super().start(st)
        c = self.cue
        st.show["card"] = {"kind": c["kind"], "t0": st.t, "dur": c["duration"] + 0.05, "c": c}
        if c["kind"] not in FIGHT_OVER:
            st.show["hud"] = False
        for when, sfx in c.get("sfx", []):
            st.sfx(sfx, st.t + when)
        if c.get("cheer"):
            st.show["cheer_until"] = st.t + c["cheer"]
        if c.get("flash"):
            st.show["flash_until"] = st.t + 0.14
            st.show["shake_until"] = st.t + 0.3

    def update(self, st):
        return self.elapsed(st) >= self.cue["duration"]


class ShowBout(tl.Task):
    """Start of a bout or round: big card, then the HUD."""

    def start(self, st):
        super().start(st)
        sh, c = st.show, self.cue
        sh.update(round=1, hud=True, caption=None, label=c.get("label", ""))
        if "score" in c:
            sh["score"] = list(c["score"])
        sh["odds_target"] = dict(c["odds"])
        sh["odds_shown"] = dict(c["odds"])
        if c.get("bar_title"):
            sh["bar_title"] = c["bar_title"]
        reset_fighters(st)
        if c.get("members"):
            sh["sides"]["b"]["members"] = list(c["members"])
            sh["sides"]["b"]["label"] = c.get("b_label", sh["sides"]["b"]["label"])
        self.dur = c.get("duration", 1.25)
        sh["card"] = {"kind": "bout", "t0": st.t, "dur": self.dur, "c": c}
        st.sfx("hit_heavy")
        st.sfx("alert", st.t + 0.15)

    def update(self, st):
        return self.elapsed(st) >= self.dur


class ShowCaption(tl.Task):
    """A caption line (initiative, eliminations). Blocks for ``hold`` seconds."""

    def start(self, st):
        super().start(st)
        c = self.cue
        st.show["caption"] = {"text": c["text"], "t0": st.t, "dur": c.get("dur", 2.4), "col": tuple(c.get("col", WHITE))}
        for when, sfx in c.get("sfx", []):
            st.sfx(sfx, st.t + when)
        if "odds" in c:
            st.show["odds_target"] = dict(c["odds"])

    def update(self, st):
        return self.elapsed(st) >= self.cue.get("hold", 0.0)


class ShowCTA(tl.Task):
    blocking = False

    def start(self, st):
        super().start(st)
        st.show["cta"] = {"t0": st.t, "dur": self.cue.get("dur", 4.0), "text": self.cue.get("text")}
        st.sfx("buff", st.t + 0.2, 0.6)

    def update(self, st):
        return True


class ShowOdds(tl.Task):
    blocking = False

    def start(self, st):
        super().start(st)
        st.show["odds_target"] = dict(self.cue["odds"])

    def update(self, st):
        return True


class ShowTurn(tl.BattleTurnTask):
    def start(self, st):
        super().start(st)
        st.show["round"] = self.cue.get("round", 1)
        self.dur = self.cue.get("hold", 0.3)


class ShowAttack(tl.BattleAttackTask):
    """The stock attack, plus what makes it a broadcast: the odds move on impact,
    crits shake the screen, the crowd reacts and a caption explains the rule."""

    def __init__(self, cue):
        super().__init__(cue)
        k = cue.get("tempo", 1.0)
        self.DUR = 1.75 * k
        self.IMPACT = 1.0 * k
        self.SPIN = 0.7 * k

    def start(self, st):
        super().start(st)
        self.fired = False
        if self.cue.get("tempo", 1.0) < 1.0 and st.ui.dice:
            st.ui.dice[-1]["dur"] = self.DUR + 0.2
            st.ui.dice[-1]["spin"] = self.SPIN

    def update(self, st):
        done = super().update(st)
        c, sh = self.cue, st.show
        if not self.fired and self.done_impact:
            self.fired = True
            if "odds" in c:
                sh["odds_target"] = dict(c["odds"])
            if c.get("critical"):
                sh["shake_until"] = st.t + 0.3
                sh["flash_until"] = st.t + 0.14
                sh["cheer_until"] = st.t + 1.4
            elif c.get("hit") and c.get("damage", 0) >= c.get("big", 99):
                sh["shake_until"] = st.t + 0.18
                sh["cheer_until"] = st.t + 0.7
            if c.get("prone") and c.get("hp_after", 1) > 0:
                self.tg.state = "down"
            if c.get("caption"):
                sh["caption"] = {"text": c["caption"], "t0": st.t + 0.1, "dur": c.get("caption_dur", 2.6),
                                 "col": tuple(c.get("caption_col", WHITE))}
        return done


class ShowKO(tl.Task):
    """End of a bout: K.O. card over the fight."""

    def start(self, st):
        super().start(st)
        sh, c = st.show, self.cue
        if "score" in c:
            sh["score"] = list(c["score"])
        sh["odds_target"] = dict(c["odds"])
        self.dur = c.get("duration", 2.6)
        sh["card"] = {"kind": "ko", "t0": st.t, "dur": self.dur, "c": c}
        sh["caption"] = None
        sh["cheer_until"] = st.t + self.dur
        sh["shake_until"] = st.t + 0.3
        sh["flash_until"] = st.t + 0.14
        st.sfx("crit")
        st.sfx("victory", st.t + 0.3, 0.7)
        if st.battle:
            st.battle.active = None

    def update(self, st):
        return self.elapsed(st) >= self.dur


class ShowReset(tl.Task):
    """Between bouts: clear the fight so the next battle_start places everyone afresh."""

    def start(self, st):
        super().start(st)
        if st.battle:
            st.end_battle()
        for fid in self.cue["fighters"]:
            st.actors.pop(fid, None)


TASKS = {"show_setup": ShowSetup, "show_card": ShowCard, "show_bout": ShowBout, "show_caption": ShowCaption,
         "show_cta": ShowCTA, "show_odds": ShowOdds, "show_turn": ShowTurn, "show_attack": ShowAttack,
         "show_ko": ShowKO, "show_reset": ShowReset}


# ================================================================ content
def avg(notation: str) -> float:
    return DiceSpec.parse(notation).average


def mon(mid: str) -> dict:
    return data.monsters()[mid]


def attack_line(m: dict) -> str:
    ids = m.get("multiattack") or [m["attacks"][0]["id"]]
    names = {a["id"]: a["name"] for a in m["attacks"]}
    if len(ids) > 1 and len(set(ids)) == 1:
        return f"{len(ids)} x {names[ids[0]]}"
    return " + ".join(names[i] for i in ids)


def damage_per_turn(m: dict) -> float:
    by = {a["id"]: a for a in m["attacks"]}
    ids = m.get("multiattack") or [max(m["attacks"], key=lambda a: avg(a["damage"]))["id"]]
    tot = 0.0
    for i in ids:
        a = by[i]
        tot += avg(a["damage"]) + sum(avg(x) for x, _ in a.get("extra_damage", []))
    return tot


def special(m: dict) -> str:
    tr = set(m.get("traits", []))
    for a in m["attacks"]:
        oh = a.get("on_hit") or {}
        if oh.get("condition") == "prone":
            return f"{a['name']} knocks prone"
        if oh.get("charge"):
            return "Charge knocks prone"
        if a.get("extra_damage"):
            return f"+{a['extra_damage'][0][0]} {a['extra_damage'][0][1]}"
    if "pack_tactics" in tr:
        return "Pack Tactics"
    if any(t.startswith("parry") for t in tr):
        return "Parry"
    if "bloodied_frenzy" in tr or "bloodied_fury" in tr or "bloodied_fury_melee" in tr:
        return "Bloodied fury"
    if "rampage" in tr:
        return "Rampage"
    if "nimble_escape" in tr:
        return "Nimble Escape"
    if "undead_fortitude" in tr:
        return "Undead Fortitude"
    if m.get("immunities"):
        return f"Immune: {m['immunities'][0]}"
    return "-"


def tape_rows(ma: dict, mb: dict, count_b: str | None = None) -> list[list]:
    def best(x, y):
        return "a" if x > y else "b" if y > x else None

    da, db = damage_per_turn(ma), damage_per_turn(mb)
    rows = [
        ["HIT POINTS", str(ma["hp"]), str(mb["hp"]) + (f" each" if count_b else ""), best(ma["hp"], mb["hp"])],
        ["ARMOR CLASS", str(ma["ac"]), str(mb["ac"]), best(ma["ac"], mb["ac"])],
        ["SPEED", f"{ma['speed']} ft", f"{mb['speed']} ft", best(ma["speed"], mb["speed"])],
        ["ATTACKS", attack_line(ma), attack_line(mb), None],
        ["DAMAGE / TURN", f"{da:g} avg", f"{db:g} avg", best(da, db)],
        ["SPECIAL", special(ma), special(mb), None],
    ]
    return rows
