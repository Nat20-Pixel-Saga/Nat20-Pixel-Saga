#!/usr/bin/env python3
"""Render each episode's YouTube Short (1080x1920) and its cover.

The highlight comes from pqc/pipeline/highlight.py (automatic, or hand-tuned
in assets/shorts/<campaign>.json). The Short replays that stretch of the
episode at a faster reading pace in the vertical layout of the trailer
(scripts/trailer.py): the show's name and the episode on top, the scene
following whoever is acting, dice and HP panels, and the dialogue re-flowed.
The first seconds carry the hook line from the episode's packaging; the last
seconds are an end card sending viewers to the full episode. The episode's own
music and sound effects play underneath.

    python3 scripts/shorts.py 9 out/                 # one episode -> out/C01-E009-short.mp4 + cover
    python3 scripts/shorts.py all out/ --preview     # every committed episode, quick and small
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc.pipeline import highlight  # noqa: E402
from pqc.render import brand  # noqa: E402
from pqc.render.assets import Assets  # noqa: E402
from pqc.render.ui import GOLD, INK, WHITE, draw_text, wrap  # noqa: E402
from pqc.render.video import render_frames  # noqa: E402

FPS = 30
SIZE = (270, 480)
HOOK_S = 3.2
END_S = 2.8
SOURCES = [ROOT / "scripts" / "shorts.py", ROOT / "scripts" / "trailer.py", ROOT / "pqc" / "pipeline" / "highlight.py"]

_spec = importlib.util.spec_from_file_location("trailer", ROOT / "scripts" / "trailer.py")
trailer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trailer)

FALLBACK = {   # used only when an episode's packaging has no "short" block
    "death_save": "ONE DEATH SAVE AT A TIME", "down": "SOMEBODY IS GOING DOWN", "revive": "GET UP. PLEASE.",
    "nat20": "NATURAL 20", "nat1": "NATURAL 1", "social": "WILL THEY BUY IT?", "social_fail": "THEY DIDN'T BUY IT",
    "fight": "ROLL FOR INITIATIVE", "kill": "STEEL AND SMALL FIRE", "story": "EVERY ROLL IS REAL"}


def episode_dir(eid: str) -> Path:
    return ROOT / "episodes" / eid


def short_meta(eid: str, pk: dict, window: dict) -> dict:
    s = dict(pk.get("short") or {})
    n = int(eid[-3:])
    title = pk["title"].split("|")[0].strip()
    s.setdefault("hook", FALLBACK.get(window["kind"], "EVERY ROLL IS REAL"))
    s.setdefault("title", f"{s['hook'].capitalize()} | Nat 20 Pixels")
    s.setdefault("description", f"A moment from Episode {n}, {title}.")
    return s


# ---------------------------------------------------------------- frames
def hook_overlay(img: Image.Image, text: str, t: float, assets: Assets) -> Image.Image:
    if t >= HOOK_S:
        return img
    a = min(1.0, t / 0.25, (HOOK_S - t) / 0.5)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = assets.font("title")
    lines = wrap(text.upper(), f, SIZE[0] - 24)[:3]
    h = 16 + 24 * len(lines)
    y0 = trailer.V_TOP + 10
    d.rounded_rectangle((8, y0, SIZE[0] - 8, y0 + h), radius=6, fill=(12, 16, 18, 225), outline=brand.MID, width=2)
    y = y0 + 9
    for line in lines:
        w = f.getlength(line)
        draw_text(d, ((SIZE[0] - w) / 2, y), line, f, GOLD, shadow=INK)
        y += 24
    if a < 1:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * max(0.0, a))))
    out = img.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


def short_frames(eid: str, assets: Assets, window: dict, meta: dict):
    """Yield the Short's frames; afterwards `audio` holds its audio events."""
    d = episode_dir(eid)
    tl = json.loads((d / "timeline.json").read_text())
    pk = json.loads((d / "packaging.json").read_text())
    n = int(eid[-3:])
    title = pk["title"].split("|")[0].strip()
    header = f"Episode {n} - {title}"
    comp = trailer.Composer(assets)
    comp.shorts_safe = True
    w = trailer.Window({"cue": window["start_cue"], "dur": window["duration_s"], "follow": True}, 0)
    runner = trailer.ClipRunner(tl, assets, [w], window.get("reading", highlight.SHORT_READING))
    count = 0
    for _, t, (_wide, world, overlay, panels, dialog, fade, focus) in runner.clips():
        img = comp.vertical(world, overlay, panels, dialog, t, fade, focus, header)
        yield hook_overlay(img, meta["hook"], count / FPS, assets)
        count += 1
    main_s = count / FPS
    card = {"card": ["NAT 20 PIXELS", f"Full episode {n}:", title, "on the channel"], "logo": True}
    m = int(round(END_S * FPS))
    for i in range(m):
        yield comp.card(SIZE, card, (i + 0.5) / m)
    # Audio: everything the episode played inside the window, plus the music already running at its start.
    t0 = w.t0
    ev = []
    running = None
    for e in sorted(runner.stage.audio, key=lambda e: e["t"]):
        if e["t"] < t0 and e["type"] in ("music", "music_stop"):
            running = e if e["type"] == "music" else None
        elif t0 <= e["t"] < t0 + main_s:
            ev.append({**e, "t": e["t"] - t0})
    if running:
        ev.append({**running, "t": 0.0, "fade_in": 0.3})
    ev += [{"type": "music_stop", "t": main_s, "fade_out": 0.4},
           {"type": "music", "id": "theme", "t": main_s, "fade_in": 0.2, "volume": 0.35}]
    short_frames.audio = ev


def render_short(eid: str, out_dir: Path, assets: Assets | None = None, preview: bool = False) -> dict:
    assets = assets or Assets()
    d = episode_dir(eid)
    tl = json.loads((d / "timeline.json").read_text())
    pk = json.loads((d / "packaging.json").read_text())
    window = highlight.highlight(eid, tl, assets)
    meta = short_meta(eid, pk, window)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = list(short_frames(eid, assets, window, meta))
    scale, preset, crf = (2, "ultrafast", 28) if preview else (4, "medium", 18)
    info = render_frames(frames, SIZE, out_dir / f"{eid}-short.mp4", short_frames.audio, assets, FPS, scale, crf, preset)
    cover = render_cover(eid, window, meta, out_dir / f"{eid}-short-cover.png", assets)
    still = frames[int(1.0 * FPS)]           # the hook frame: the best in-video cover
    still.resize((SIZE[0] * 4, SIZE[1] * 4), Image.NEAREST).save(out_dir / f"{eid}-short-frame.png")
    return {**info, "cover": str(cover), "window": window, "meta": meta}


# ----------------------------------------------------------------- cover
def render_cover(eid: str, window: dict, meta: dict, out: Path, assets: Assets) -> Path:
    n = int(eid[-3:])
    spec = highlight.short_spec(eid)
    frame, st = trailer.scene_frame(n, window["anchor_cue"], 1.2, assets, window.get("reading"))
    img = Image.new("RGBA", (1080, 1920), brand.BG)
    logo = brand.lockup(assets, stacked=True, scale=4)
    img.alpha_composite(logo, ((1080 - logo.width) // 2, 60))
    cue = json.loads((episode_dir(eid) / "timeline.json").read_text())["cues"][window["anchor_cue"]]
    focus = cue.get("speaker") or cue.get("actor") or (window["speakers"] or [None])[0]
    scene = trailer.zoomed(frame, st, focus, (1080, 900))
    top = 60 + logo.height + 50
    img.alpha_composite(scene, (0, top))
    d = ImageDraw.Draw(img)
    d.rectangle((0, top, 1079, top + 899), outline=brand.MID, width=6)
    # Portraits overlapping the bottom edge of the scene.
    faces = spec.get("faces") or [s for s in window["speakers"] if s in highlight.PARTY][:2]
    fs, gap = 6, 24
    cards = []
    for who in faces[:3]:
        try:
            face = assets.actor(who).faceset
        except Exception:
            face = None
        if face is not None:
            big = face.resize((38 * fs, 38 * fs), Image.NEAREST)
            c = Image.new("RGBA", (big.width + 16, big.height + 16), (20, 27, 27, 255))
            ImageDraw.Draw(c).rectangle((0, 0, c.width - 1, c.height - 1), outline=brand.MID, width=6)
            c.alpha_composite(big, (8, 8))
            cards.append(c)
    if cards:
        total = sum(c.width for c in cards) + gap * (len(cards) - 1)
        x = (1080 - total) // 2
        y = top + 900 - cards[0].height // 2
        for c in cards:
            img.alpha_composite(c, (x, y))
            x += c.width + gap
        y_text = y + cards[0].height + 50
    else:
        y_text = top + 950
    f = assets.font_at("title", 104)
    lines = wrap(meta["hook"].upper(), f, 1000)[:3]
    for line in lines:
        ff = f
        while d.textlength(line, font=ff) > 1000:
            ff = assets.font_at("title", ff.size - 6)
        trailer.outline_text(d, ((1080 - d.textlength(line, font=ff)) / 2, y_text), line, ff, (255, 214, 102))
        y_text += 112
    small = assets.font_at("title", 40)
    label = f"EPISODE {n}"
    lw = d.textlength(label, font=small)
    d.rounded_rectangle(((1080 - lw) / 2 - 28, 1920 - 130, (1080 + lw) / 2 + 28, 1920 - 62), 14,
                        fill=(20, 27, 27, 235), outline=brand.MID, width=3)
    draw_text(d, ((1080 - lw) / 2, 1920 - 124), label, small, WHITE)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", help="episode number in Campaign 1, an id like C01-E003, or 'all'")
    ap.add_argument("out_dir")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    if a.episode == "all":
        eids = sorted(p.name for p in (ROOT / "episodes").glob("C??-E???") if (p / "timeline.json").exists())
    else:
        eids = [f"C01-E{int(a.episode):03d}" if a.episode.isdigit() else a.episode]
    assets = Assets()
    for eid in eids:
        info = render_short(eid, Path(a.out_dir), assets, a.preview)
        print(f"{eid}: {info['duration_s']} s, cues {info['window']['start_cue']}-{info['window']['end_cue']} "
              f"({info['window']['kind']}), hook {info['meta']['hook']!r}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
