#!/usr/bin/env python3
"""Arena duel: two creatures, best of three, decided by the seeded rules engine.

    python scripts/arena_duel.py                       # Brown Bear vs Dire Wolf, 1080p
    python scripts/arena_duel.py --scale 2 --samples 80  # quick preview

The format, in order: a 3-second hook, the tale of the tape, the engine's odds
from thousands of simulated fights, then the bouts with a live win-chance bar,
one-line rule captions and a crowd that reacts, and a result card with the
numbers and a call for the next matchup. The seed is derived from the matchup,
never picked after looking at the result.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc import data  # noqa: E402
from pqc.arena.duel import run_match  # noqa: E402
from pqc.dice import Dice, DiceSpec  # noqa: E402
from pqc.render import stage as stage_mod  # noqa: E402
from pqc.render import timeline as tl  # noqa: E402
from pqc.render.assets import Assets  # noqa: E402
from pqc.render.director import battle_cues  # noqa: E402
from pqc.render.stage import Stage  # noqa: E402
from pqc.render.tilemap import TileMap  # noqa: E402
from pqc.render.ui import GOLD, GREY, UI, WHITE, H, W, draw_text  # noqa: E402

MAP = "arena_pit"
A_COL = (236, 142, 58, 255)
B_COL = (92, 164, 236, 255)
DARK = (20, 27, 27, 235)
CROWD_SPRITES = ["villager_a", "soldier", "villager_b", "miller", "villager_c", "soldier_b", "soldier_c"]


# ----------------------------------------------------------------- drawing
# Tiny5 is drawn on an 8-pixel grid, so it is only crisp at multiples of 8. Every
# duel overlay uses it at 8, 16, 32 or 48: the digits have to be unmistakable.
def _f(st_or_assets, size: int):
    a = getattr(st_or_assets, "a", st_or_assets)
    return a.font_at("small", size)


def _center(d, x, y, text, font, fill, shadow=(20, 27, 27, 255)):
    draw_text(d, (int(x - font.getlength(text) / 2), int(y)), text, font, fill, shadow=shadow)


def _right(d, x, y, text, font, fill):
    draw_text(d, (int(x - font.getlength(text)), int(y)), text, font, fill, shadow=(20, 27, 27, 255))


def _left(d, x, y, text, font, fill):
    draw_text(d, (int(x), int(y)), text, font, fill, shadow=(20, 27, 27, 255))


def _slam(st, d, x, y, text, size: int, fill, age: float, dur: float = 0.18, grow: float = 0.8):
    """Text that lands: drawn oversized, settling to ``size`` over ``dur`` seconds."""
    s = 1.0 + grow * (1 - _ease(age / dur))
    px = size if s < 1.02 else max(8, int(size * s / 8) * 8)
    _center(d, x, y - (px - size) / 2, text, _f(st, px), fill)


def _ease(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


def _face(st: Stage, sprite: str, scale: int = 1, flip: bool = False) -> Image.Image:
    f = st.a.actor(sprite).faceset
    if flip:
        f = f.transpose(Image.FLIP_LEFT_RIGHT)
    return f.resize((f.width * scale, f.height * scale), Image.NEAREST) if scale != 1 else f


def _odds_bar(d, x0, y0, x1, y1, p: float):
    mid = int(round(x0 + (x1 - x0) * p))
    d.rectangle((x0 - 1, y0 - 1, x1 + 1, y1 + 1), fill=(20, 27, 27, 255))
    d.rectangle((x0, y0, mid, y1), fill=A_COL)
    d.rectangle((mid, y0, x1, y1), fill=B_COL)
    d.rectangle((mid - 1, y0 - 2, mid, y1 + 2), fill=WHITE)


def _score_line(du) -> str:
    return f"{du['a']['name']}  {du['score'][0]} - {du['score'][1]}  {du['b']['name']}"


def _panel(d, side: str, st: Stage, du: dict):
    f = du[side]
    left = side == "a"
    x0 = 4 if left else W - 112
    d.rounded_rectangle((x0, 4, x0 + 108, 46), radius=3, fill=DARK, outline=f["col"])
    tx = x0 + 44 if left else x0 + 4
    _left(d, tx, 6, f["name"].upper(), _f(st, 8), f["col"])
    hp, mx, ghost = f["hp_shown"], f["max_hp"], f["hp_ghost"]
    bx0, bx1 = tx, tx + 60
    d.rectangle((bx0, 17, bx1, 24), fill=(59, 54, 67, 255))
    frac, gfrac = max(0.0, hp / mx), max(0.0, ghost / mx)
    col = (116, 163, 52, 255) if frac > 0.5 else GOLD if frac > 0.25 else (209, 75, 52, 255)
    for fr, c in ((gfrac, WHITE), (frac, col)):
        if fr > 0:
            w = max(1, int(60 * fr))
            d.rectangle((bx0, 17, bx0 + w, 24) if left else (bx1 - w, 17, bx1, 24), fill=c)
    _left(d, tx, 27, f"{int(round(hp))}", _f(st, 16), WHITE)
    _left(d, tx + 22, 34, f"/{mx}", _f(st, 8), GREY)
    for i in range(du["need"]):              # bouts won
        px = tx + 62 - (du["need"] - i) * 9
        won = i < du["score"][0 if left else 1]
        d.rectangle((px, 31, px + 6, 37), fill=GOLD if won else (59, 54, 67, 255), outline=(20, 27, 27, 255))


def _draw_fight_hud(layer: Image.Image, st: Stage, du: dict):
    d = ImageDraw.Draw(layer)
    for side in ("a", "b"):
        _panel(d, side, st, du)
        f = du[side]
        layer.alpha_composite(_face(st, f["sprite"], flip=side == "b"), (6 if side == "a" else W - 44, 6))
    if not st.ui.dice:                        # round marker where the dice tray lands
        text = f"BOUT {du['bout']}  -  ROUND {du['round']}"
        tw = _f(st, 8).getlength(text)
        d.rounded_rectangle((W / 2 - tw / 2 - 8, 5, W / 2 + tw / 2 + 8, 19), radius=3, fill=DARK)
        _center(d, W / 2, 8, text, _f(st, 8), GOLD)
    # Win chance.
    p = du["odds_shown"]
    d.rectangle((0, H - 28, W, H), fill=(20, 27, 27, 225))
    _odds_bar(d, 58, H - 14, W - 58, H - 6, p)
    _center(d, W / 2, H - 26, "CHANCE TO WIN THE MATCH", _f(st, 8), GREY)
    _left(d, 8, H - 20, f"{int(round(p * 100))}%", _f(st, 16), du["a"]["col"])
    _right(d, W - 8, H - 20, f"{int(round((1 - p) * 100))}%", _f(st, 16), du["b"]["col"])
    cap = du.get("caption")
    if cap and cap["t0"] <= st.t <= cap["t0"] + cap["dur"]:
        age = st.t - cap["t0"]
        font = _f(st, 16)
        if font.getlength(cap["text"]) > W - 24:
            font = _f(st, 8)
        tw = font.getlength(cap["text"])
        y = H - 52 + int((1 - _ease(age / 0.15)) * 8)
        d.rounded_rectangle((W / 2 - tw / 2 - 8, y, W / 2 + tw / 2 + 8, y + 19), radius=3, fill=DARK,
                            outline=cap.get("col", GOLD))
        _center(d, W / 2, y + (2 if font.size == 16 else 6), cap["text"], font, cap.get("col", WHITE))


def _draw_hook(layer, st, du, age, dur):
    d = ImageDraw.Draw(layer)
    d.rectangle((0, 50, W, 220), fill=(20, 27, 27, 215))
    big = _f(st, 48)
    ax = -300 + (W / 2 + 300) * _ease(age / 0.3)
    bx = W + 300 - (W / 2 + 300) * _ease((age - 0.25) / 0.3)
    _center(d, ax, 52, du["a"]["name"].upper(), big, du["a"]["col"])
    if age > 0.25:
        _center(d, bx, 138, du["b"]["name"].upper(), big, du["b"]["col"])
    if age > 0.6:
        _slam(st, d, W / 2, 110, "VS", 32, GOLD, age - 0.6, grow=1.0)
    if age > 1.0:
        txt = f"BEST OF {du['best_of']}  /  REAL DICE  /  NO REROLLS"
        n = int((age - 1.0) * 45)
        _center(d, W / 2, 196, txt if n >= len(txt) else txt[:n], _f(st, 16), WHITE)


def _rows(d, st, rows, y0: int, step: int, age: float, t0: float, gap: float, cols) -> None:
    """Stat rows revealed one at a time: value, label, value."""
    for i, row in enumerate(rows):
        if age < t0 + i * gap:
            break
        label, va, vb = row[0], row[1], row[2]
        best = row[3] if len(row) > 3 else None
        y = y0 + i * step
        fresh = age - (t0 + i * gap) < 0.12
        d.rectangle((38, y, W - 38, y + step - 2), fill=(42, 42, 50, 255) if i % 2 == 0 else (29, 34, 37, 255))
        _center(d, W / 2, y + 4, label, _f(st, 8), GREY)
        ca = WHITE if fresh else GOLD if best == "a" else cols[0]
        cb = WHITE if fresh else GOLD if best == "b" else cols[1]
        _right(d, W / 2 - 52, y, va, _f(st, 16), ca)
        _left(d, W / 2 + 52, y, vb, _f(st, 16), cb)


def _draw_tape(layer, st, du, age, dur):
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((28, 10, W - 28, H - 10), radius=5, fill=(20, 27, 27, 240), outline=GOLD)
    _center(d, W / 2, 14, "TALE OF THE TAPE", _f(st, 16), GOLD)
    layer.alpha_composite(_face(st, du["a"]["sprite"], 2), (52, 36))
    layer.alpha_composite(_face(st, du["b"]["sprite"], 2, flip=True), (W - 52 - 76, 36))
    _center(d, 90, 116, du["a"]["name"].upper(), _f(st, 8), du["a"]["col"])
    _center(d, W - 90, 116, du["b"]["name"].upper(), _f(st, 8), du["b"]["col"])
    _center(d, W / 2, 56, "VS", _f(st, 32), WHITE)
    _rows(d, st, du["tape"], 132, 20, age, 0.6, 0.5, (WHITE, WHITE))


def _draw_odds(layer, st, du, age, dur):
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((28, 40, W - 28, H - 40), radius=5, fill=(20, 27, 27, 240), outline=GOLD)
    _center(d, W / 2, 48, f"WE RAN THIS FIGHT {du['prior_n']:,} TIMES", _f(st, 16), GOLD)
    p = 0.5 + (du["p_fresh"] - 0.5) * _ease((age - 0.5) / 1.3)
    _left(d, 70, 78, du["a"]["name"].upper(), _f(st, 8), du["a"]["col"])
    _right(d, W - 70, 78, du["b"]["name"].upper(), _f(st, 8), du["b"]["col"])
    _odds_bar(d, 70, 90, W - 70, 110, p)
    _left(d, 70, 116, f"{int(round(p * 100))}%", _f(st, 32), du["a"]["col"])
    _right(d, W - 70, 116, f"{int(round((1 - p) * 100))}%", _f(st, 32), du["b"]["col"])
    if age > 1.9:
        fav = du["a"] if du["p_match"] >= 0.5 else du["b"]
        pm = max(du["p_match"], 1 - du["p_match"])
        _center(d, W / 2, 160, f"Best of {du['best_of']}: {fav['name']} wins {int(round(pm * 100))}% of the time.",
                _f(st, 16), WHITE)
    if age > 2.8:
        _center(d, W / 2, 190, "Pick your side in the comments!", _f(st, 16), GOLD)


def _draw_bout(layer, st, du, age, dur):
    d = ImageDraw.Draw(layer)
    d.rectangle((0, 90, W, 178), fill=(20, 27, 27, 220))
    final = du["bout"] == du["best_of"] and du["score"][0] == du["score"][1]
    _slam(st, d, W / 2, 92, "FINAL BOUT" if final else f"BOUT {du['bout']}", 48, GOLD, age)
    _center(d, W / 2, 152, _score_line(du), _f(st, 16), WHITE)


def _draw_ko(layer, st, du, age, dur):
    d = ImageDraw.Draw(layer)
    w = du["ko"]
    d.rectangle((0, 76, W, 192), fill=(20, 27, 27, 225))
    _slam(st, d, W / 2, 76, "K.O.", 48, (236, 90, 70, 255), age, dur=0.15, grow=1.2)
    if age > 0.45:
        _center(d, W / 2, 136, f"BOUT {du['bout']} GOES TO {w['name'].upper()}", _f(st, 16), w["col"])
    if age > 0.8:
        _center(d, W / 2, 164, _score_line(du), _f(st, 16), WHITE)


def _draw_final(layer, st, du, age, dur):
    d = ImageDraw.Draw(layer)
    fin = du["final"]
    w, l = fin["winner"], fin["loser"]
    d.rounded_rectangle((28, 8, W - 28, H - 8), radius=5, fill=(20, 27, 27, 242), outline=w["col"])
    layer.alpha_composite(_face(st, w["sprite"], 2), (48, 20))
    _left(d, 140, 18, "WINNER", _f(st, 16), GOLD)
    _left(d, 140, 34, w["name"].upper(), _f(st, 32), w["col"])
    _left(d, 140, 74, f"{fin['score'][0]} - {fin['score'][1]}  over {l['name']}", _f(st, 16), WHITE)
    _rows(d, st, fin["rows"], 106, 20, age, 1.0, 0.4, (du["a"]["col"], du["b"]["col"]))
    if age > 3.0:
        _center(d, W / 2, 192, f"Seed {fin['seed']}. Every roll is in the public log.", _f(st, 8), GREY)
    if age > 3.8:
        _center(d, W / 2, 208, "Who fights next? Comment a matchup.", _f(st, 16), GOLD)
    if age > 4.6:
        _center(d, W / 2, 232, "The most-liked one goes in the pit.", _f(st, 16), WHITE)


CARDS = {"hook": _draw_hook, "tape": _draw_tape, "odds": _draw_odds, "bout": _draw_bout, "ko": _draw_ko,
         "final": _draw_final}


def _overlay(st: Stage, frame: Image.Image) -> Image.Image:
    du = st.duel
    t = st.t
    dt = 1.0 / st.fps
    # Ease the odds and the HP bars toward their targets.
    du["odds_shown"] += (du["odds_target"] - du["odds_shown"]) * min(1.0, dt * 6)
    for side in ("a", "b"):
        f = du[side]
        if st.battle and f["id"] in st.battle.hp:
            f["hp"] = st.battle.hp[f["id"]][0]
        f["hp_shown"] += (f["hp"] - f["hp_shown"]) * min(1.0, dt * 14)
        if f["hp_ghost"] > f["hp_shown"]:
            f["hp_ghost"] = max(f["hp_shown"], f["hp_ghost"] - f["max_hp"] * dt * 0.45)
        else:
            f["hp_ghost"] = f["hp_shown"]
    # The crowd: idle shuffles, and everybody jumps for a crit or a knockout.
    for i, cid in enumerate(du["crowd"]):
        a = st.actors.get(cid)
        if not a:
            continue
        if t < du["cheer_until"]:
            a.dy = -abs(math.sin(t * 11 + i * 1.7)) * 3
        else:
            ph = (t * 0.8 + i * 0.61) % 3.7
            a.dy = -math.sin(ph / 0.28 * math.pi) * 2 if ph < 0.28 else 0
    img = frame.convert("RGBA")
    if t < du["shake_until"]:
        k = (du["shake_until"] - t) / 0.3
        img = ImageChops.offset(img, int(round(math.sin(t * 95) * 4 * k)), int(round(math.cos(t * 80) * 3 * k)))
    if t < du["flash_until"]:
        img.alpha_composite(Image.new("RGBA", img.size, (255, 255, 255, int(150 * (du["flash_until"] - t) / 0.14))))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    card = du.get("card")
    if card and card["t0"] <= t < card["t0"] + card["dur"]:
        CARDS[card["kind"]](layer, st, du, t - card["t0"], card["dur"])
        if card["kind"] in ("bout", "ko"):
            hud = Image.new("RGBA", img.size, (0, 0, 0, 0))
            _draw_fight_hud(hud, st, du)
            img.alpha_composite(hud)
    elif du["hud"]:
        _draw_fight_hud(layer, st, du)
    if st.fade > 0:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * (1 - min(1.0, st.fade)))))
    img.alpha_composite(layer)
    return img.convert("RGB")


def install():
    """Hook the duel overlay into the renderer (this process only)."""
    orig = Stage.render

    def render(self, clean: bool = False):
        frame = orig(self, clean)
        return _overlay(self, frame) if getattr(self, "duel", None) and not clean else frame

    Stage.render = render
    stage_mod._enemy_bars = lambda canvas, st: None      # the duel HUD replaces these
    UI.draw_hud = lambda self, canvas, t, members: None
    UI.draw_banner = lambda self, canvas, t: None
    tl.TASKS.update({"duel_setup": DuelSetup, "duel_card": DuelCard, "duel_bout": DuelBout, "duel_ini": DuelIni,
                     "duel_turn": DuelTurn, "duel_attack": DuelAttack, "duel_ko": DuelKO, "duel_reset": DuelReset})


# -------------------------------------------------------------------- cues
class DuelSetup(tl.Task):
    def start(self, st):
        super().start(st)
        c = self.cue
        st.duel = {"hud": False, "card": None, "caption": None, "odds_shown": c["odds"], "odds_target": c["odds"],
                   "shake_until": -1, "flash_until": -1, "cheer_until": -1, "bout": 1, "round": 1,
                   "score": [0, 0], "crowd": c["crowd"], **c["static"]}
        for side in ("a", "b"):
            f = st.duel[side]
            f.update(hp=f["max_hp"], hp_shown=f["max_hp"], hp_ghost=f["max_hp"], col=tuple(f["col"]))
        # The stock dice tray and damage popups, in the grid-true font (see the note on _f).
        st.ui.f_text = st.ui.f_pop = st.ui.f_num = _f(st, 16)
        st.ui.f_small = _f(st, 8)


class DuelCard(tl.Task):
    """Full-screen card: hook, tape, odds, final. Sound cues ride along as [seconds, sfx id]."""

    def start(self, st):
        super().start(st)
        c = self.cue
        st.duel["card"] = {"kind": c["kind"], "t0": st.t, "dur": c["duration"] + 0.05}
        st.duel["hud"] = False
        if "final" in c:
            st.duel["final"] = c["final"]
            for k in ("winner", "loser"):
                c["final"][k]["col"] = tuple(c["final"][k]["col"])
        for when, sfx in c.get("sfx", []):
            st.sfx(sfx, st.t + when)
        if c.get("cheer"):
            st.duel["cheer_until"] = st.t + c["cheer"]

    def update(self, st):
        return self.elapsed(st) >= self.cue["duration"]


class DuelBout(tl.Task):
    DUR = 1.25

    def start(self, st):
        super().start(st)
        du, c = st.duel, self.cue
        du.update(bout=c["n"], round=1, score=list(c["score"]), odds_target=c["odds"], hud=True, caption=None)
        for side in ("a", "b"):
            f = du[side]
            f.update(hp=f["max_hp"], hp_shown=f["max_hp"], hp_ghost=f["max_hp"])
        du["card"] = {"kind": "bout", "t0": st.t, "dur": self.DUR}
        st.sfx("hit_heavy")
        st.sfx("alert", st.t + 0.15)

    def update(self, st):
        return self.elapsed(st) >= self.DUR


class DuelIni(tl.Task):
    """Initiative in one line: both totals, and who goes first."""
    DUR = 1.7

    def start(self, st):
        super().start(st)
        c = self.cue
        st.duel["caption"] = {"text": c["text"], "t0": st.t, "dur": self.DUR + 0.6, "col": tuple(c["col"])}
        st.sfx("dice_roll")
        st.sfx("dice_land", st.t + 0.5)

    def update(self, st):
        return self.elapsed(st) >= self.DUR


class DuelTurn(tl.BattleTurnTask):
    def start(self, st):
        super().start(st)
        st.duel["round"] = self.cue.get("round", 1)
        self.dur = 0.3


class DuelAttack(tl.BattleAttackTask):
    """The stock attack, plus what makes it a broadcast: the odds move on impact,
    crits shake the screen, the crowd reacts and a caption explains the rule."""
    DUR = 1.75

    def start(self, st):
        super().start(st)
        self.fired = False

    def update(self, st):
        done = super().update(st)
        c, du = self.cue, st.duel
        if not self.fired and self.done_impact:
            self.fired = True
            if "odds_after" in c:
                du["odds_target"] = c["odds_after"]
            if c.get("critical"):
                du["shake_until"] = st.t + 0.3
                du["flash_until"] = st.t + 0.14
                du["cheer_until"] = st.t + 1.4
            elif c.get("hit") and c.get("damage", 0) >= c.get("big", 99):
                du["shake_until"] = st.t + 0.18
                du["cheer_until"] = st.t + 0.7
            if c.get("prone") and c.get("hp_after", 1) > 0:
                self.tg.state = "down"
            if c.get("caption"):
                du["caption"] = {"text": c["caption"], "t0": st.t + 0.1, "dur": c.get("caption_dur", 2.6),
                                 "col": tuple(c.get("caption_col", WHITE))}
        return done


class DuelKO(tl.Task):
    DUR = 2.6

    def start(self, st):
        super().start(st)
        du, c = st.duel, self.cue
        du["score"] = list(c["score"])
        du["odds_target"] = c["odds"]
        du["ko"] = du[c["winner"]]
        du["card"] = {"kind": "ko", "t0": st.t, "dur": self.DUR}
        du["caption"] = None
        du["cheer_until"] = st.t + self.DUR
        du["shake_until"] = st.t + 0.3
        du["flash_until"] = st.t + 0.14
        st.sfx("crit")
        st.sfx("victory", st.t + 0.3, 0.7)
        if st.battle:
            st.battle.active = None

    def update(self, st):
        return self.elapsed(st) >= self.DUR


class DuelReset(tl.Task):
    """Between bouts: clear the fight so the next battle_start places both fighters afresh."""

    def start(self, st):
        super().start(st)
        if st.battle:
            st.end_battle()
        for fid in self.cue["fighters"]:
            st.actors.pop(fid, None)


# ----------------------------------------------------------------- content
def _avg(notation: str) -> float:
    return DiceSpec.parse(notation).average


def tape_rows(ma: dict, mb: dict) -> list[list]:
    def atk_names(m):
        ids = m.get("multiattack") or [m["attacks"][0]["id"]]
        return " + ".join(i.title() for i in ids)

    def dmg(m):
        by = {a["id"]: a for a in m["attacks"]}
        ids = m.get("multiattack") or [m["attacks"][0]["id"]]
        return sum(_avg(by[i]["damage"]) for i in ids)

    def special(m):
        for a in m["attacks"]:
            if (a.get("on_hit") or {}).get("condition") == "prone":
                return f"{a['name']} knocks prone"
        return "-"

    def best(x, y):
        return "a" if x > y else "b" if y > x else None

    da, db = dmg(ma), dmg(mb)
    return [
        ["HIT POINTS", str(ma["hp"]), str(mb["hp"]), best(ma["hp"], mb["hp"])],
        ["ARMOR CLASS", str(ma["ac"]), str(mb["ac"]), best(ma["ac"], mb["ac"])],
        ["SPEED", f"{ma['speed']} ft", f"{mb['speed']} ft", best(ma["speed"], mb["speed"])],
        ["ATTACKS", atk_names(ma), atk_names(mb), best(len(ma.get("multiattack") or [1]), len(mb.get("multiattack") or [1]))],
        ["DAMAGE / TURN", f"{da:g} avg", f"{db:g} avg", best(da, db)],
        ["SPECIAL", special(ma), special(mb), None],
    ]


def bout_cues(bout: dict, n: int, a: dict, b: dict, first: bool, need: int) -> list[dict]:
    names = {a["id"]: a["name"], b["id"]: b["name"]}
    cues = battle_cues(bout, kinds={a["id"]: a["sprite"], b["id"]: b["sprite"]}, names=names,
                       attack_types=bout["attack_types"], music="battle_boss" if first else None, origin=(0, 0))
    events = bout["events"]
    rolls = {r["id"]: r for r in bout["rolls"]}
    snap_seqs = sorted(bout["match_odds"])

    def odds_at(seq):
        return bout["match_odds"][next(s for s in snap_seqs if s >= seq)]

    attacks = [e for e in events if e["t"] == "attack" and not e.get("blocked")]
    ini = {e["actor"]: e["total"] for e in events if e["t"] == "initiative"}
    order = next(e["order"] for e in events if e["t"] == "initiative_order")
    out = [{"op": "duel_bout", "n": n, "score": bout["score_before"], "odds": bout["match_odds_start"]}]
    seen: set[str] = set()
    prev = bout["match_odds_start"]
    ai = 0
    for cue in cues:
        op = cue["op"]
        if op == "initiative":
            fst = a if order[0] == a["id"] else b
            out.append({"op": "duel_ini", "col": fst["col"],
                        "text": f"Initiative {ini[a['id']]} v {ini[b['id']]}: {fst['name']} goes first."})
        elif op == "battle_turn":
            out.append({**cue, "op": "duel_turn"})
        elif op == "battle_attack":
            ev = attacks[ai]
            ai += 1
            roll = rolls[ev["roll"]]
            tgt = a if ev["target"] == a["id"] else b
            act = a if ev["actor"] == a["id"] else b
            now = odds_at(ev["seq"])
            cue = {**cue, "op": "duel_attack", "odds_after": now, "big": 10,
                   "prone": ev.get("condition_applied") == "prone"}
            swing = now - prev
            lead = a if now >= 0.5 else b
            cap = None
            if ev.get("critical"):
                cap = ("Natural 20! Damage dice are doubled.", GOLD)
            elif roll.get("natural") == 1:
                cap = ("Natural 1: automatic miss.", GREY)
            elif ev.get("hit") and ev["damage"]["hp_after"] <= 0:
                cap = None
            elif ev.get("condition_applied") == "prone" and "prone" not in seen:
                seen.add("prone")
                cap = (f"Knocked prone! Attacks on it roll two d20s.", WHITE)
            elif abs(swing) >= 0.15:
                cap = (f"Big swing: {lead['name']} now {int(round(max(now, 1 - now) * 100))}% to win.", lead["col"])
            elif ev.get("hit") and 0 < ev["damage"]["hp_after"] <= tgt["max_hp"] * 0.3 and f"low{tgt['id']}" not in seen:
                seen.add(f"low{tgt['id']}")
                cap = (f"{tgt['name']} on {ev['damage']['hp_after']} HP. One hit ends it.", WHITE)
            elif roll.get("advantage") == "advantage" and "adv" not in seen:
                seen.add("adv")
                cap = ("Advantage: two d20s, keep the best.", WHITE)
            elif roll.get("advantage") == "disadvantage" and "dis" not in seen:
                seen.add("dis")
                cap = ("Disadvantage: two d20s, keep the worst.", WHITE)
            if cap:
                cue["caption"], cue["caption_col"] = cap[0], list(cap[1])
            prev = now
            out.append(cue)
        elif op == "battle_end":
            win = "a" if bout["winner"] == "party" else "b"
            final = max(bout["score_after"]) >= need
            out.append({"op": "duel_ko", "winner": win, "score": bout["score_after"],
                        "odds": (1.0 if win == "a" else 0.0) if final else
                        bout["match_odds"][snap_seqs[-1]]})
            out.append({"op": "fade", "to": "black", "duration": 0.25})
            out.append({"op": "duel_reset", "fighters": [a["id"], b["id"]]})
        else:
            out.append(cue)
    return out


def match_stats(match: dict, a: dict, b: dict) -> list[list[str]]:
    s = {a["id"]: {"att": 0, "hit": 0, "crit": 0, "dmg": 0, "max": 0}, b["id"]: {"att": 0, "hit": 0, "crit": 0, "dmg": 0, "max": 0}}
    for bout in match["bouts"]:
        for e in bout["events"]:
            if e["t"] == "attack" and not e.get("blocked"):
                r = s[e["actor"]]
                r["att"] += 1
                if e["hit"]:
                    r["hit"] += 1
                    r["crit"] += bool(e["critical"])
                    r["dmg"] += e["damage"]["total"]
                    r["max"] = max(r["max"], e["damage"]["total"])
    x, y = s[a["id"]], s[b["id"]]
    return [["ATTACKS LANDED", f"{x['hit']} of {x['att']}", f"{y['hit']} of {y['att']}"],
            ["CRITICAL HITS", str(x["crit"]), str(y["crit"])],
            ["BIGGEST HIT", str(x["max"]), str(y["max"])],
            ["TOTAL DAMAGE", str(x["dmg"]), str(y["dmg"])]]


def build_timeline(a: dict, b: dict, seed: str, best_of: int, samples: int, prior_n: int, assets: Assets) -> tuple[dict, dict]:
    tm = TileMap.load(MAP, assets)
    crowd_pts = sorted((k for k in tm.points if k.startswith("crowd_")), key=lambda k: int(k.split("_")[1]))
    facing = json.loads((ROOT / "assets" / "maps" / f"{MAP}.json").read_text())["crowd_facing"]
    blocked = set(tm.blocked(assets)) | {tuple(tm.points[k]) for k in crowd_pts}
    a = {**a, "pos": tuple(tm.points["bear_start"])}
    b = {**b, "pos": tuple(tm.points["wolf_start"])}
    match = run_match(a, b, seed, best_of=best_of, blocked=blocked, samples=samples, prior_n=prior_n)
    for bout in match["bouts"]:
        assert Dice.verify_log(bout["seed"], bout["rolls"]), "roll log does not replay"
    need = best_of // 2 + 1
    ma, mb = data.monsters()[a["monster"]], data.monsters()[b["monster"]]
    a.update(max_hp=ma["hp"])
    b.update(max_hp=mb["hp"])
    static = {"a": {k: a[k] for k in ("id", "name", "sprite", "col", "max_hp")},
              "b": {k: b[k] for k in ("id", "name", "sprite", "col", "max_hp")},
              "best_of": best_of, "need": need, "tape": tape_rows(ma, mb), "p_fresh": match["p_fresh"],
              "prior_n": prior_n, "p_match": match["bouts"][0]["match_odds_start"]}
    cues: list[dict] = [
        {"op": "scene", "map": MAP, "time_of_day": "day", "camera": tm.points["center"]},
        {"op": "fade", "from": "black", "to": "clear", "duration": 0.35, "wait": False},
    ]
    crowd_ids = []
    for i, k in enumerate(crowd_pts):
        cues.append({"op": "spawn", "actor": k, "sprite": CROWD_SPRITES[(i * 3) % len(CROWD_SPRITES)],
                     "at": tm.points[k], "facing": facing[k]})
        crowd_ids.append(k)
    cues += [
        {"op": "spawn", "actor": a["id"], "sprite": a["sprite"], "at": list(a["pos"]), "facing": "right"},
        {"op": "spawn", "actor": b["id"], "sprite": b["sprite"], "at": list(b["pos"]), "facing": "left"},
        {"op": "duel_setup", "static": static, "crowd": crowd_ids, "odds": static["p_match"]},
        {"op": "music", "track": "tension", "fade_in": 0.2, "volume": 0.55},
        {"op": "duel_card", "kind": "hook", "duration": 3.2, "cheer": 3.2,
         "sfx": [[0.0, "hit_heavy"], [0.25, "hit_heavy"], [0.6, "crit"]]},
        {"op": "duel_card", "kind": "tape", "duration": 5.0,
         "sfx": [[0.0, "transition"]] + [[0.6 + i * 0.5, "dice_land"] for i in range(6)]},
        {"op": "duel_card", "kind": "odds", "duration": 4.8,
         "sfx": [[0.0, "transition"], [0.5, "dice_roll"], [1.8, "dice_land"], [2.8, "alert"]]},
        {"op": "music_stop", "fade_out": 0.3},
        {"op": "duel_reset", "fighters": [a["id"], b["id"]]},
    ]
    for i, bout in enumerate(match["bouts"]):
        if i:
            cues.append({"op": "fade", "from": "black", "to": "clear", "duration": 0.25, "wait": False})
        cues += bout_cues(bout, i + 1, a, b, first=i == 0, need=need)
    win, lose = (a, b) if match["winner"] == a["id"] else (b, a)
    cues = cues[:-2]                                   # keep the last fight on screen behind the result
    cues += [
        {"op": "music_stop", "fade_out": 0.4},
        {"op": "music", "track": "theme", "fade_in": 0.4, "volume": 0.5},
        {"op": "duel_card", "kind": "final", "duration": 9.0, "cheer": 9.0, "sfx": [[0.0, "level_up"]],
         "final": {"winner": {k: win[k] for k in ("name", "sprite", "col")},
                   "loser": {k: lose[k] for k in ("name", "sprite", "col")},
                   "score": sorted(match["score"], reverse=True), "rows": match_stats(match, a, b), "seed": seed}},
        {"op": "music_stop", "fade_out": 0.8},
        {"op": "fade", "to": "black", "duration": 0.8},
    ]
    title = f"{a['name']} vs {b['name']}"
    return ({"schema": "pqc/timeline@1", "id": "arena_duel", "title": title, "fps": 30, "seed": seed, "tail": 0.2,
             "cues": cues}, match)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="brown_bear")
    ap.add_argument("--b", default="dire_wolf")
    ap.add_argument("--number", type=int, default=1, help="arena episode number (part of the seed)")
    ap.add_argument("--best-of", type=int, default=3)
    ap.add_argument("--samples", type=int, default=300, help="replays behind each win-chance update")
    ap.add_argument("--prior", type=int, default=5000, help="simulated fights behind the opening odds")
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "render_out" / "arena_duel.mp4"))
    ap.add_argument("--stills", default="")
    args = ap.parse_args()
    mons = data.monsters()
    a = {"id": "a", "monster": args.a, "name": mons[args.a]["name"], "sprite": args.a, "col": list(A_COL)}
    b = {"id": "b", "monster": args.b, "name": mons[args.b]["name"], "sprite": args.b, "col": list(B_COL)}
    seed = f"ARENA-{args.number:03d}-{args.a}-vs-{args.b}"
    install()
    assets = Assets()
    timeline, match = build_timeline(a, b, seed, args.best_of, args.samples, args.prior, assets)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    log = {"seed": seed, "best_of": args.best_of, "opening_odds": {"fights": args.prior, "a_wins": match["p_fresh"]},
           "score": match["score"], "winner": match["winner"],
           "bouts": [{"seed": bo["seed"], "winner": bo["winner"], "rounds": bo["rounds"], "rolls": bo["rolls"],
                      "events": bo["events"]} for bo in match["bouts"]]}
    out.with_suffix(".rolls.json").write_text(json.dumps(log, indent=1, ensure_ascii=False))
    out.with_suffix(".timeline.json").write_text(json.dumps(timeline, indent=1, ensure_ascii=False))
    print(f"{timeline['title']}: {match['score']}  opening odds {match['p_fresh']:.3f}  seed {seed}")
    from pqc.render.video import render
    dry = tl.Runner(timeline, assets)
    for _ in dry.frames(render=False):
        pass
    marks = [(t, c) for t, c in zip(dry.cue_times, timeline["cues"]) if c["op"] in ("duel_card", "duel_bout", "duel_ko")]
    chapters = ["0:00 The matchup"]
    for t, c in marks:
        if c["op"] == "duel_bout":
            chapters.append(f"{int(t) // 60}:{int(t) % 60:02d} Bout {c['n']}")
        elif c.get("kind") == "final":
            chapters.append(f"{int(t) // 60}:{int(t) % 60:02d} Result and stats")
    out.with_suffix(".chapters.txt").write_text("\n".join(chapters) + "\n")
    print("marks:", [(round(t, 1), c.get("kind", c["op"])) for t, c in marks])
    if args.stills == "auto":
        stills = [0.5, 2.6] + [round(t + (6.5 if c.get("kind") == "final" else 1.6 if c["op"] == "duel_ko"
                                          else 0.9 * c.get("duration", 1.2)), 2)
                               for t, c in marks if c.get("kind") != "hook"]
    else:
        stills = [float(s) for s in args.stills.split(",") if s]
    render(timeline, out, assets=assets, scale=args.scale, stills=stills, stills_dir=out.parent / "stills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
