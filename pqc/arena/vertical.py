"""The Pit's Shorts (1080x1920): a trailer the day before each episode and two highlights after it.

Every clip is the episode itself, replayed from its timeline and re-composed for
9:16: the episode's title on top, both fighters' panels, a 270x270 window on the
fight that follows the action, the dice tray, and the live win chance. The
bottom 12% is left clear for YouTube's title and buttons.

* Trailer (day before): hook, tale of the tape, the odds, the opening of the
  first bout cut off at a cliffhanger, "WHO WINS?", then when to watch.
* Highlight A (day after): the decisive finish, through the K.O.
* Highlight B (two days after): the biggest swing of the win chance, or a
  natural 20; failing both, the odds against the result.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from ..render.assets import Assets
from ..render.ui import GOLD, GREY, WHITE, W as WW, _draw_dice_tray
from . import produce as P
from . import season as SE
from . import show as S

VW, VH = 270, 480
FPS = 30
BG = (12, 16, 18, 255)
Y_HEAD, Y_PANEL, Y_SCENE, Y_DICE, Y_ODDS = 0, 38, 82, 354, 404


# ================================================================= layout
def _font(st, size):
    return S.font(st, size)


def header(img, st, title: str, kicker: str = "THE PIT"):
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, VW, Y_PANEL - 2), fill=(20, 27, 27, 255))
    S.center(d, VW / 2, 4, kicker, _font(st, 8), GOLD)
    f = S.fit(st, title, VW - 12, (24, 16, 8))
    S.center(d, VW / 2, 14 + (24 - f.size) // 2, title, f, WHITE)


def panels(img, st):
    sh = st.show
    d = ImageDraw.Draw(img)
    d.rectangle((0, Y_PANEL, VW, Y_SCENE - 2), fill=(20, 27, 27, 255))
    if sh["fmt"] == "rumble":
        teams = sorted(sh["fighters"].values(), key=lambda f: -sh["odds_shown"].get(f["team"], 0))
        alive = [f for f in teams if f["hp"] > 0]
        S.center(d, VW / 2, Y_PANEL + 2, f"{len(alive)} LEFT  -  CHANCE TO WIN", _font(st, 8), GREY)
        for i, f in enumerate(alive[:3]):
            x = 6 + i * 88
            ic = S.icon(st, f["sprite"])
            if ic.height > 16:
                ic = ic.resize((max(1, ic.width * 16 // ic.height), 16), Image.NEAREST)
            img.alpha_composite(ic, (x, Y_PANEL + 16))
            S.left(d, x + 20, Y_PANEL + 14, f["short"][:8].upper(), _font(st, 8), f["col"])
            S.left(d, x + 20, Y_PANEL + 24, S.pct(sh["odds_shown"].get(f["team"], 0)), _font(st, 16), WHITE)
        return
    for side in ("a", "b"):
        s = sh["sides"][side]
        is_a = side == "a"
        x0 = 2 if is_a else VW // 2 + 1
        w = VW // 2 - 3
        d.rounded_rectangle((x0, Y_PANEL + 1, x0 + w, Y_SCENE - 4), radius=3, fill=S.DARK, outline=s["col"])
        fc = S.face(st, s["sprite"], flip=not is_a)
        img.alpha_composite(fc, (x0 + 2 if is_a else x0 + w - 40, Y_PANEL + 3))
        tx = x0 + 42 if is_a else x0 + 4
        S.left(d, tx, Y_PANEL + 4, s["label"].upper()[:11], _font(st, 8), s["col"])
        members = [sh["fighters"][m] for m in s["members"]]
        if len(members) == 1:
            f = members[0]
            frac = max(0.0, f["hp_shown"] / f["max_hp"])
            g = max(0.0, f["hp_ghost"] / f["max_hp"])
            d.rectangle((tx, Y_PANEL + 15, tx + 84, Y_PANEL + 21), fill=(59, 54, 67, 255))
            for fr, c in ((g, WHITE), (frac, S.hp_color(frac))):
                if fr > 0:
                    ww = max(1, int(84 * fr))
                    d.rectangle((tx, Y_PANEL + 15, tx + ww, Y_PANEL + 21) if is_a else
                                (tx + 84 - ww, Y_PANEL + 15, tx + 84, Y_PANEL + 21), fill=c)
            S.left(d, tx, Y_PANEL + 24, str(int(round(f["hp_shown"]))), _font(st, 16), WHITE)
            S.left(d, tx + 26, Y_PANEL + 31, f"/{f['max_hp']}", _font(st, 8), GREY)
        else:
            standing = sum(1 for f in members if f["hp"] > 0)
            S.left(d, tx, Y_PANEL + 14, str(standing), _font(st, 16), WHITE)
            S.left(d, tx + 22, Y_PANEL + 21, f"/ {len(members)} LEFT", _font(st, 8), GREY)
            for i, f in enumerate(members):
                px, py = tx + (i % 7) * 12, Y_PANEL + 31 + (i // 7) * 5
                d.rectangle((px, py, px + 10, py + 3), fill=(59, 54, 67, 255))
                frac = max(0.0, f["hp_shown"] / f["max_hp"])
                if frac > 0:
                    d.rectangle((px, py, px + max(1, int(10 * frac)), py + 3), fill=S.hp_color(frac))
        if sh.get("need"):
            for i in range(sh["need"]):
                px = tx + 50 + i * 8
                py = Y_SCENE - 12
                won = i < sh["score"][0 if is_a else 1]
                d.rectangle((px, py, px + 5, py + 5), fill=GOLD if won else (59, 54, 67, 255), outline=(20, 27, 27, 255))


def scene(img, st, wide: Image.Image):
    """A square window on the fight: the whole height of the frame, or twice as close when the fighters
    stand together."""
    sh = st.show
    z = max(1.0, min(2.0, sh.get("zoom") or 1.0))
    size = 270 / z
    cx = sh.get("crop_x") or WW / 2
    cy = sh.get("crop_y") or 135
    x0 = min(max(cx - size / 2, 0), WW - size)
    y0 = min(max(cy - size / 2, 0), 270 - size)
    win = wide.crop((int(round(x0)), int(round(y0)), int(round(x0 + size)), int(round(y0 + size))))
    img.paste(win.resize((270, 270), Image.NEAREST).convert("RGBA"), (0, Y_SCENE))


def dice(img, st):
    d = ImageDraw.Draw(img)
    d.rectangle((0, Y_DICE, VW, Y_ODDS - 1), fill=(20, 27, 27, 255))
    live = [dd for dd in st.ui.dice if st.t <= dd["t0"] + dd["dur"]]
    if not live:
        sh = st.show
        txt = (sh["label"] + "  -  " if sh["label"] else "") + f"ROUND {sh['round']}"
        S.center(d, VW / 2, Y_DICE + 18, txt, _font(st, 8), GOLD)
        return
    tmp = Image.new("RGBA", (WW, 60), (0, 0, 0, 0))
    _draw_dice_tray(st.ui, tmp, live[-1], st.t)
    img.alpha_composite(tmp.crop((116, 6, 332, 54)), (27, Y_DICE + 1))


def odds(img, st):
    sh = st.show
    d = ImageDraw.Draw(img)
    d.rectangle((0, Y_ODDS, VW, Y_ODDS + 26), fill=(20, 27, 27, 255))
    if sh["fmt"] == "rumble":
        teams = sorted(sh["fighters"].values(), key=lambda f: -sh["odds_shown"].get(f["team"], 0))
        x = 10
        d.rectangle((9, Y_ODDS + 13, VW - 9, Y_ODDS + 23), fill=(20, 27, 27, 255))
        for f in teams:
            w = (VW - 20) * sh["odds_shown"].get(f["team"], 0)
            if w >= 1:
                d.rectangle((int(x), Y_ODDS + 14, int(x + w), Y_ODDS + 22), fill=f["col"])
            x += w
        S.center(d, VW / 2, Y_ODDS + 2, "CHANCE TO WIN", _font(st, 8), GREY)
        return
    p = sh["odds_shown"].get("a", 0.5)
    sa, sb = sh["sides"]["a"], sh["sides"]["b"]
    S.odds_bar(d, 46, Y_ODDS + 14, VW - 46, Y_ODDS + 22, p, sa["col"], sb["col"])
    S.center(d, VW / 2, Y_ODDS + 2, "CHANCE TO WIN", _font(st, 8), GREY)
    S.left(d, 4, Y_ODDS + 9, S.pct(p), _font(st, 16), sa["col"])
    S.right(d, VW - 4, Y_ODDS + 9, S.pct(1 - p), _font(st, 16), sb["col"])


def caption(img, st):
    cap = st.show.get("caption")
    if not cap or not (cap["t0"] <= st.t <= cap["t0"] + cap["dur"]):
        return
    d = ImageDraw.Draw(img)
    words, lines, cur = cap["text"].split(), [], ""
    f = _font(st, 8)
    for w in words:
        if f.getlength((cur + " " + w).strip()) > VW - 24:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    y = Y_DICE - 8 - 12 * len(lines)
    w = max(f.getlength(l) for l in lines)
    d.rounded_rectangle((VW / 2 - w / 2 - 6, y - 3, VW / 2 + w / 2 + 6, y + 12 * len(lines) + 1), radius=3,
                        fill=S.DARK, outline=cap.get("col", GOLD))
    for i, l in enumerate(lines):
        S.center(d, VW / 2, y + i * 12, l, f, cap.get("col", WHITE))


def big_over_scene(img, st, text, col, sub=None, age=1.0):
    d = ImageDraw.Draw(img)
    d.rectangle((0, Y_SCENE + 92, VW, Y_SCENE + 92 + (74 if sub else 56)), fill=(20, 27, 27, 220))
    f = S.fit(st, text, VW - 12, (48, 32, 24, 16))
    S.slam(st, d, VW / 2, Y_SCENE + 98 + (48 - f.size) // 2, text, f.size, col, age)
    if sub:
        fs = S.fit(st, sub, VW - 12, (16, 8))
        S.center(d, VW / 2, Y_SCENE + 148, sub, fs, WHITE)


def compose(st, wide: Image.Image, title: str, hook: str | None = None, hook_age: float = 0.0) -> Image.Image:
    img = Image.new("RGBA", (VW, VH), BG)
    scene(img, st, wide)
    header(img, st, title)
    sh = st.show
    if sh.get("fighters"):
        panels(img, st)
        dice(img, st)
        odds(img, st)
        caption(img, st)
    card = sh.get("card")
    if card and card["t0"] <= st.t < card["t0"] + card["dur"]:
        c, age = card["c"], st.t - card["t0"]
        if card["kind"] == "ko":
            big_over_scene(img, st, c.get("big", "K.O."), tuple(c.get("big_col", S.RED)), c.get("line"), age)
        elif card["kind"] == "bout":
            big_over_scene(img, st, c["title"], GOLD, c.get("sub"), age)
    if hook and hook_age < 2.8:
        d = ImageDraw.Draw(img)
        a = min(1.0, hook_age / 0.12) if hook_age < 2.5 else max(0.0, (2.8 - hook_age) / 0.3)
        if a > 0:
            f = S.fit(st, hook, VW - 16, (32, 24, 16))
            words = hook.split()
            lines = [hook] if f.size >= 24 or len(words) < 3 else [" ".join(words[:len(words) // 2]),
                                                                   " ".join(words[len(words) // 2:])]
            f = S.fit(st, max(lines, key=len), VW - 16, (32, 24, 16))
            h = len(lines) * (f.size + 6) + 10
            y0 = Y_SCENE + 8
            d.rectangle((0, y0, VW, y0 + h), fill=(20, 27, 27, int(220 * a)))
            for i, l in enumerate(lines):
                S.center(d, VW / 2, y0 + 6 + i * (f.size + 6), l, f, GOLD)
    if st.fade > 0:
        img.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, int(255 * min(1.0, st.fade)))))
    return img


# ================================================================== cards
def card_frame(st, kind: str, c: dict, age: float, title: str) -> Image.Image:
    img = Image.new("RGBA", (VW, VH), BG)
    d = ImageDraw.Draw(img)
    header(img, st, title)
    y = Y_PANEL + 10
    if kind == "hook":
        top, mid, bot = c["lines"]
        ca, cb = tuple(c.get("ca", S.A_COL)), tuple(c.get("cb", S.B_COL))
        ft = S.fit(st, top, VW - 12, (48, 32, 24, 16))
        fb = S.fit(st, bot, VW - 12, (48, 32, 24, 16))
        x1 = -200 + (VW / 2 + 200) * S.ease(age / 0.3)
        x2 = VW + 200 - (VW / 2 + 200) * S.ease((age - 0.2) / 0.3)
        S.center(d, x1, 120, top, ft, ca)
        if age > 0.45:
            S.slam(st, d, VW / 2, 120 + ft.size + 18, mid, 24, GOLD, age - 0.45)
        if age > 0.2:
            S.center(d, x2, 120 + ft.size + 60, bot, fb, cb)
        if age > 1.0 and c.get("sprites"):
            fa = S.face(st, c["sprites"][0], 2)
            img.alpha_composite(fa, (VW // 2 - fa.width - 6, 260))
            if len(c["sprites"]) > 1:
                fb2 = S.face(st, c["sprites"][1], 2, flip=True)
                img.alpha_composite(fb2, (VW // 2 + 6, 260))
        if age > 1.2:
            S.center(d, VW / 2, 352, c.get("tag", "WHO WINS?"), _font(st, 24), WHITE)
            S.center(d, VW / 2, 384, c.get("tag2", "REAL DICE. NO REROLLS."), _font(st, 8), GREY)
    elif kind == "tape":
        img.alpha_composite(S.face(st, c["a"]["sprite"], 2), (16, y))
        img.alpha_composite(S.face(st, c["b"]["sprite"], 2, flip=True), (VW - 16 - 76, y))
        S.center(d, VW / 2, y + 28, "VS", _font(st, 24), WHITE)
        S.center(d, 54, y + 80, c["a"]["name"].upper()[:13], _font(st, 8), tuple(c["a"]["col"]))
        S.center(d, VW - 54, y + 80, c["b"]["name"].upper()[:13], _font(st, 8), tuple(c["b"]["col"]))
        for i, row in enumerate(c["rows"]):
            if age < 0.4 + i * 0.35:
                break
            yy = y + 100 + i * 34
            d.rectangle((6, yy, VW - 6, yy + 30), fill=S.ROW_A if i % 2 == 0 else S.ROW_B)
            S.center(d, VW / 2, yy + 3, row[0], _font(st, 8), GREY)
            fa = _font(st, 16) if _font(st, 16).getlength(str(row[1])) < 120 else _font(st, 8)
            fb = _font(st, 16) if _font(st, 16).getlength(str(row[2])) < 120 else _font(st, 8)
            best = row[3] if len(row) > 3 else None
            S.left(d, 12, yy + 13 + (16 - fa.size) // 2, str(row[1]), fa, GOLD if best == "a" else WHITE)
            S.right(d, VW - 12, yy + 13 + (16 - fb.size) // 2, str(row[2]), fb, GOLD if best == "b" else WHITE)
    elif kind == "odds":
        S.center(d, VW / 2, y + 6, c["title"], S.fit(st, c["title"], VW - 12, (16, 8)), GOLD)
        if c.get("kind_card") == "two":
            p = 0.5 + (c["p"] - 0.5) * S.ease((age - 0.4) / 1.2)
            ca, cb = tuple(c["a"]["col"]), tuple(c["b"]["col"])
            S.left(d, 14, y + 40, c["a"]["name"].upper()[:13], _font(st, 8), ca)
            S.right(d, VW - 14, y + 40, c["b"]["name"].upper()[:13], _font(st, 8), cb)
            S.odds_bar(d, 14, y + 52, VW - 14, y + 74, p, ca, cb)
            S.left(d, 14, y + 82, S.pct(p), _font(st, 32), ca)
            S.right(d, VW - 14, y + 82, S.pct(1 - p), _font(st, 32), cb)
            if age > 1.6 and c.get("line"):
                _wrap_center(d, st, c["line"], y + 140, WHITE)
        else:
            rows = c["rows"] if c.get("kind_card") == "ramp" else sorted(c["rows"], key=lambda r: -r[1])
            for i, row in enumerate(rows[:8]):
                if age < 0.3 + i * 0.2:
                    break
                yy = y + 34 + i * 30
                label, p = row[0], row[1]
                col = tuple(row[2]) if len(row) > 2 else tuple(c.get("col", S.A_COL))
                S.left(d, 10, yy, str(label).upper()[:20], _font(st, 8), col if len(row) > 2 else WHITE)
                g = S.ease((age - 0.3 - i * 0.2) / 0.5)
                d.rectangle((10, yy + 11, 200, yy + 21), fill=(59, 54, 67, 255))
                d.rectangle((10, yy + 11, 10 + int(190 * p * g), yy + 21), fill=col)
                S.left(d, 208, yy + 8, S.pct(p), _font(st, 16), WHITE)
        if age > 2.2 and c.get("cta"):
            _wrap_center(d, st, c["cta"], 372, GOLD)
    elif kind == "end":
        lines = c["lines"]
        f0 = S.fit(st, lines[0], VW - 16, (32, 24, 16))
        S.slam(st, d, VW / 2, 110, lines[0], f0.size, GOLD, age)
        for i, l in enumerate(lines[1:]):
            if age > 0.4 + 0.3 * i:
                _wrap_center(d, st, l, 160 + i * 40, WHITE if i else GOLD, (24, 16, 8))
        if age > 0.9:
            btn = S.subscribe_button(st, pressed=age > 2.2)
            img.alpha_composite(btn, (VW // 2 - btn.width // 2, 330))
            S.center(d, VW / 2, 360, c.get("foot", "NEW FIGHTS EVERY WED AND SAT"), _font(st, 8), GREY)
    elif kind == "freeze":
        pass
    return img


def _wrap_center(d, st, text, y, col, sizes=(16, 8)):
    f = S.fit(st, text, VW - 16, sizes)
    if f.getlength(text) <= VW - 16:
        S.center(d, VW / 2, y, text, f, col)
        return
    f = S.font(st, sizes[0] if len(sizes) == 1 else sizes[-2] if len(sizes) > 2 else sizes[0])
    words, lines, cur = text.split(), [], ""
    for w in words:
        if f.getlength((cur + " " + w).strip()) > VW - 16:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    for i, l in enumerate(lines):
        S.center(d, VW / 2, y + i * (f.size + 4), l, f, col)


# =================================================================== clips
def clip(timeline: dict, assets: Assets, t0: float, t1: float, title: str, hook: str | None = None):
    """Frames of the episode between t0 and t1 in the vertical layout, and the audio events in that window
    (relative to t0), with whatever music was already playing at t0."""
    S.install()
    r = S.ShowRunner(timeline, assets)
    r.layout = "tall"
    r.render_from = t0
    frames = []
    for f in r.frames():
        st = r.stage
        if f is None:
            continue
        if st.t > t1:
            break
        frames.append(compose(st, f, title, hook, st.t - t0))
    ev, running = [], None
    for e in sorted(r.stage.audio, key=lambda e: e["t"]):
        if e["t"] < t0 and e["type"] in ("music", "music_stop"):
            running = e if e["type"] == "music" else None
        elif t0 <= e["t"] < t1:
            ev.append({**e, "t": e["t"] - t0})
    if running:
        ev.append({**running, "t": 0.0, "fade_in": 0.2})
    return frames, ev, r.stage


def still_card(st, kind, c, dur, title):
    n = int(round(dur * FPS))
    return [card_frame(st, kind, c, (i + 0.5) / FPS, title) for i in range(n)]


def freeze(frame: Image.Image, st, text: str, dur: float) -> list[Image.Image]:
    out = []
    n = int(round(dur * FPS))
    for i in range(n):
        img = frame.copy()
        a = min(1.0, (i + 1) / 6)
        img.alpha_composite(Image.new("RGBA", img.size, (12, 16, 18, int(150 * a))))
        d = ImageDraw.Draw(img)
        S.slam(st, d, VW / 2, Y_SCENE + 100, text, 32, GOLD, i / FPS)
        out.append(img)
    return out


# ============================================================== selections
def _times(timeline, times):
    return list(zip(times, timeline["cues"]))


def _title(season, ep) -> str:
    return ep["title"].upper() if len(ep["title"]) <= 26 else ep.get("short_title", " ".join(ep["hook"])).upper()


def trailer(season, n, res, timeline, times, out: Path, assets: Assets, preview=False) -> dict:
    ep = SE.episode(season, n)
    title = ep.get("short_title", _title(season, ep))
    tc = _times(timeline, times)
    cards = {c["kind"]: c for _, c in tc if c["op"] == "show_card"}
    bout0 = next((t, c) for t, c in tc if c["op"] == "show_bout")
    t_bout = bout0[0]
    ko0 = next(t for t, c in tc if c["op"] == "show_ko")
    attacks = [(t, c) for t, c in tc if c["op"] == "show_attack" and t_bout < t < ko0 - 2.5]
    # Cliffhanger: the biggest swing or crit 8-16 s into the first bout (else ~13 s in).
    cand = [(t, c) for t, c in attacks if 8 <= t - t_bout <= 17]
    best = None
    if cand:
        best = max(cand, key=lambda tc_: (tc_[1].get("meta", {}).get("crit", False),
                                          tc_[1].get("meta", {}).get("swing", False), -abs(tc_[0] - t_bout - 13)))
    t_end = (best[0] + 1.35) if best else min(t_bout + 13, ko0 - 1.5)
    S.install()
    frames, ev, st = clip(timeline, assets, t_bout, t_end, title)
    hook_c = {"lines": ep["hook"], "sprites": [s for s in (ep.get("a") or ep.get("star") or ep.get("thumb_a"),
                                                         ep.get("b") or ep.get("minion_sprite") or ep.get("minion") or ep.get("thumb_b")) if s],
              "tag": ep.get("short_tag", "WHO WINS?" if ep["kind"] != "how_many" else "HOW MANY?")}
    pre = still_card(st, "hook", hook_c, 2.8, title)
    if "tape" in cards:
        pre += still_card(st, "tape", {**cards["tape"], "rows": [r for r in cards["tape"]["rows"]
                                                                 if r[0] in ("HIT POINTS", "ARMOR CLASS", "DAMAGE / TURN", "SPECIAL")]},
                          3.6, title)
    if "odds" in cards:
        pre += still_card(st, "odds", {**cards["odds"], "cta": None}, 3.4, title)
    cliff = freeze(frames[-1], st, "WHO WINS?" if ep["kind"] != "how_many" else "HOW MANY?", 1.6)
    import datetime as dt
    if ep.get("date"):
        d = dt.date.fromisoformat(ep["date"])
        when = f"{SE.DAYS[d.weekday()]} {d.day} {SE.MONTHS[d.month - 1]}"
    else:
        when = f"{ep.get('unlock_subscribers', 100)} SUBSCRIBER BONUS"
    end = still_card(st, "end", {"lines": ["FULL FIGHT", f"TOMORROW {season['video_time']}",
                                           ep.get("trailer_cta", "COMMENT YOUR PICK"), when]}, 3.4, title)
    allf = pre + frames + cliff + end
    t_clip = len(pre) / FPS
    audio = [{"type": "music", "id": "tension", "t": 0.0, "fade_in": 0.1, "volume": 0.55},
             {"type": "music_stop", "t": t_clip, "fade_out": 0.2},
             {"type": "sfx", "id": "hit_heavy", "t": 0.0, "volume": 1.0}, {"type": "sfx", "id": "crit", "t": 0.5, "volume": 1.0},
             {"type": "sfx", "id": "transition", "t": 2.8, "volume": 1.0}, {"type": "sfx", "id": "dice_roll", "t": 6.6, "volume": 1.0},
             {"type": "sfx", "id": "dice_land", "t": 7.6, "volume": 1.0}]
    audio += [{**e, "t": e["t"] + t_clip} for e in ev if e["type"] != "music_stop"]
    t_cliff = t_clip + len(frames) / FPS
    audio += [{"type": "music_stop", "t": t_cliff, "fade_out": 0.15}, {"type": "sfx", "id": "alert", "t": t_cliff, "volume": 1.0},
              {"type": "music", "id": "theme", "t": t_cliff + 1.6, "fade_in": 0.2, "volume": 0.45}]
    scale, preset, crf = (2, "veryfast", 24) if preview else (4, "medium", 18)
    info = P.encode(allf, (VW, VH), out, audio, assets, FPS, scale, crf, preset)
    allf[int(1.6 * FPS)].resize((VW * 4, VH * 4), Image.NEAREST).save(out.with_suffix(".cover.png"))
    return {**info, "kind": "trailer", "clip": [round(t_bout, 2), round(t_end, 2)]}


def _end_after(season, ep):
    nxt = next((e for e in season["episodes"] if e["n"] == ep["n"] + 1), None)
    lines = ["FULL FIGHT", "ON THE CHANNEL", "TAP THE LINK ABOVE"]
    if nxt:
        lines.append(f"NEXT: {SE.short_date(nxt['date'])}")
    return {"lines": lines}


def highlight(season, n, res, timeline, times, out: Path, assets: Assets, which: str, preview=False) -> dict:
    ep = SE.episode(season, n)
    title = ep.get("short_title", _title(season, ep))
    tc = _times(timeline, times)
    kos = [(t, c) for t, c in tc if c["op"] == "show_ko"]
    final_ko = next(((t, c) for t, c in reversed(kos) if c.get("meta", {}).get("final")), kos[-1])
    bouts = [(t, c) for t, c in tc if c["op"] == "show_bout"]
    attacks = [(t, c) for t, c in tc if c["op"] == "show_attack"]
    hook = None
    if which == "a":
        t_ko, c_ko = final_ko
        start_b = max(t for t, _ in bouts if t < t_ko)
        t0, t1 = max(start_b + 1.3, t_ko - 15.0), t_ko + 2.6
        kind = ep["kind"]
        if kind == "how_many":
            seg = res[n]["segments"][0]
            hook = f"IT TOOK {seg['answer']} {ep.get('plural', 'OF THEM').upper()}" if seg["answer"] else "UNSTOPPABLE"
        elif kind == "rumble":
            hook = "THE LAST TWO STANDING" if True else ""
        elif kind == "crown_final":
            hook = "THE CROWN-WINNING BLOW"
        else:
            hook = ep.get("hook_a", "THE DECIDING BLOW")
    else:
        lo_a = final_ko[0] - 16
        cands = []
        for i, (t, c) in enumerate(attacks):
            if lo_a <= t <= final_ko[0] + 3:
                continue
            prev = attacks[i - 1][1]["odds"] if i and attacks[i - 1][0] > max((tb for tb, _ in bouts if tb <= t), default=0) \
                else None
            now = c["odds"]
            if prev is None:
                continue
            if "a" in now:
                sw = abs(now["a"] - prev.get("a", now["a"]))
                desc = (prev.get("a", 0.5), now["a"])
            else:
                lead = max(now, key=now.get)
                sw = abs(now[lead] - prev.get(lead, 0))
                desc = None
            cands.append((sw + (0.25 if c.get("critical") else 0), t, c, desc))
        if cands:
            sw, t, c, desc = max(cands, key=lambda x: x[0])
            t0, t1 = max(t - 7.5, max(tb for tb, _ in bouts if tb <= t) + 1.3), t + 4.0
            if c.get("critical"):
                hook = "NATURAL 20!"
            elif desc:
                p0, p1 = desc
                if (p0 - 0.5) * (p1 - 0.5) < 0:
                    hook = "THE MOMENT IT FLIPPED"
                else:
                    f0, f1 = max(p0, 1 - p0), (p1 if p0 >= 0.5 else 1 - p1)
                    hook = f"{S.pct(f0)} FAVOURITE IN TROUBLE" if f1 < f0 else f"FROM {S.pct(1 - f0)} TO {S.pct(1 - f1)}"
            else:
                hook = "THE TURNING POINT"
        else:
            t, c = attacks[len(attacks) // 2]
            t0, t1 = t - 6, t + 4
            hook = "EVERY ROLL IS REAL"
    S.install()
    frames, ev, st = clip(timeline, assets, t0, t1, title, hook)
    end = still_card(st, "end", _end_after(season, ep), 3.0, title)
    allf = frames + end
    t_end = len(frames) / FPS
    audio = list(ev) + [{"type": "music_stop", "t": t_end, "fade_out": 0.3},
                        {"type": "music", "id": "theme", "t": t_end, "fade_in": 0.2, "volume": 0.45}]
    scale, preset, crf = (2, "veryfast", 24) if preview else (4, "medium", 18)
    info = P.encode(allf, (VW, VH), out, audio, assets, FPS, scale, crf, preset)
    allf[min(len(allf) - 1, int(1.0 * FPS))].resize((VW * 4, VH * 4), Image.NEAREST).save(out.with_suffix(".cover.png"))
    return {**info, "kind": f"highlight-{which}", "hook": hook, "clip": [round(t0, 2), round(t1, 2)]}


def timeline_side_name(tc, side):
    for _, c in tc:
        if c["op"] == "show_setup" and c["static"].get("sides"):
            return c["static"]["sides"][side]["label"]
    return side


def render_shorts(season, n, res, timeline, times, out_dir: Path, assets: Assets, preview=False) -> list[dict]:
    stem = f"pit-s1e{n:02d}"
    out = [trailer(season, n, res, timeline, times, out_dir / f"{stem}-trailer-short.mp4", assets, preview),
           highlight(season, n, res, timeline, times, out_dir / f"{stem}-short-a.mp4", assets, "a", preview),
           highlight(season, n, res, timeline, times, out_dir / f"{stem}-short-b.mp4", assets, "b", preview)]
    return out
