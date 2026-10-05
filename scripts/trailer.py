#!/usr/bin/env python3
"""Cut a trailer from the episodes' own timelines, in two formats at once:
16:9 (1920x1080) for the channel and 9:16 (1080x1920) for Shorts.

    python3 scripts/trailer.py assets/timelines/trailer_c01.json out/            # both formats
    python3 scripts/trailer.py assets/timelines/trailer_c01.json out/ --only wide
    python3 scripts/trailer.py ... --preview      # 2x scale, fast encode, contact sheets only

A trailer spec (pqc/trailer@1) is a list of *shots*. A shot is either a title
card (`card`: lines of text) or a window into an episode: `ep` (episode number
in Campaign 1), `cue` (index into that episode's timeline cues; the window
starts when the cue starts) and `dur` seconds. Shots marked `wide_only` are
dropped from the vertical cut, which keeps Shorts under a minute. The episodes
are replayed with a faster reading pace (`reading`), so lines type quickly;
their own music is dropped and the spec's `music` plays instead (a negative
`t` counts from the end). Dice, blips and sound effects inside each window are
kept, so every roll in the trailer is the real one from the episode.

The vertical cut shows the same frames re-composed: a header with the show's
name and the episode, the middle 270 px of the scene (following the speaker),
and the dialogue re-flowed in a narrower box underneath.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc.render.assets import Assets  # noqa: E402
from pqc.render.audio import mix, write_wav  # noqa: E402
from pqc.render.stage import _draw_wipe, _enemy_bars  # noqa: E402
from pqc.render.timeline import Runner  # noqa: E402
from pqc.render.ui import GOLD, INK, WHITE, d20_icon, draw_text, wrap  # noqa: E402
from pqc.render.ui import H as W_H, W as W_W  # noqa: E402

V_W, V_H = 270, 480            # vertical canvas (scaled 4x to 1080x1920)
V_TOP, V_SCENE = 52, 270       # header height; the scene is a 270x270 crop
BOX_FILL = (242, 234, 241, 255)
BOX_EDGE = (150, 83, 64, 255)
BOX_EDGE2 = (255, 173, 93, 255)
TEXT_INK = (60, 54, 67, 255)
PAPER_INK = (40, 34, 30, 255)


# ---------------------------------------------------------------- shots
class Window:
    def __init__(self, shot: dict, index: int):
        self.shot, self.index = shot, index
        self.cue = shot["cue"]
        self.dur = shot["dur"]
        self.t0: float | None = None      # episode time when the cue starts
        self.focus = W_W / 2              # vertical crop centre (canvas px), eased


class ClipRunner(Runner):
    """Runs an episode and hands back frames only inside the requested windows."""

    def __init__(self, timeline, assets, windows: list[Window], reading: dict):
        tl = dict(timeline)
        tl["reading"] = {**timeline.get("reading", {}), **reading}
        super().__init__(tl, assets)
        self.windows = windows
        self.n_cues = 0

    def clips(self):
        """Yield (window, episode_t, frame_pair) for every frame inside a window."""
        st = self.stage
        for frame in self.frames(render=False):      # render=False: we render ourselves
            if len(self.cue_times) > self.n_cues:
                self.n_cues = len(self.cue_times)
                for w in self.windows:
                    if w.t0 is None and self.n_cues > w.cue:
                        w.t0 = self.cue_times[w.cue]
            for w in self.windows:
                if w.t0 is not None and w.t0 <= st.t < w.t0 + w.dur:
                    yield w, st.t, self._render_pair(w)
                    break
            if all(w.t0 is not None and st.t >= w.t0 + w.dur for w in self.windows):
                return

    def _render_pair(self, w: Window):
        st = self.stage
        wide = st.render()                                    # normal 480x270 RGB frame
        world = st.render(clean=True)                         # scene only
        hud = None
        if st.mode == "battle" and st.battle:
            hud = [{"name": st.battle.names[i], "hp": st.battle.hp[i][0], "max_hp": st.battle.hp[i][1]}
                   for i in st.battle.party]
            _enemy_bars(world, st)
        overlay = Image.new("RGBA", world.size, (0, 0, 0, 0))
        ui = st.ui
        ui.draw_popups(overlay, st.t)          # these sit on world positions: cropped with the scene
        ui.draw_card(overlay, st.t)
        # The panels are drawn separately and re-placed in the vertical frame.
        panels = {}
        if hud:
            layer = Image.new("RGBA", world.size, (0, 0, 0, 0))
            ui.draw_hud(layer, st.t, hud)
            panels["hud"] = layer.crop((W_W - 132, 6, W_W - 4, 14 + 13 * len(hud)))
        if ui.initiative and ui.initiative["t0"] <= st.t <= ui.initiative["t0"] + ui.initiative["dur"]:
            layer = Image.new("RGBA", world.size, (0, 0, 0, 0))
            ui.draw_initiative(layer, st.t)
            panels["initiative"] = layer.crop((8, 28, 142, 48 + 13 * len(ui.initiative["order"])))
        layer = Image.new("RGBA", world.size, (0, 0, 0, 0))
        ui.draw_dice(layer, st.t)
        if layer.getbbox():
            panels["dice"] = layer.crop((116, 0, 332, 56))
        if st.wipe:
            _draw_wipe(world, st.wipe, st.t)
        # Follow the speaker (or the active creature) in the vertical crop.
        target = W_W / 2
        who = w.shot.get("focus")
        if not who:
            cue = self.timeline["cues"][w.cue]
            who = cue.get("speaker") or cue.get("attacker") or cue.get("caster") or cue.get("actor")
            if st.mode == "battle" and st.battle and st.battle.active in st.actors:
                who = st.battle.active if cue["op"].startswith("battle") else who
        if who in st.actors and st.actors[who].visible:
            cx, _ = st._camera()
            target = (st.actors[who].x - cx) * 2
        w.focus += (target - w.focus) * 0.12
        return wide, world, overlay, panels, ui.dialog, st.fade, w.focus


# ------------------------------------------------------------ composing
class Composer:
    def __init__(self, assets: Assets):
        self.a = assets
        self.f_title = assets.font("title")
        self.f_text = assets.font("text")
        self.f_small = assets.font("small")
        self.f_logo = assets.font_at("title", 28)
        self.arrow = assets.ui("arrow")

    # Title cards -------------------------------------------------------
    def card(self, size: tuple[int, int], shot: dict, p: float) -> Image.Image:
        W, H = size
        img = Image.new("RGBA", size, (12, 16, 18, 255))
        d = ImageDraw.Draw(img)
        alpha = min(1.0, p / 0.18, (1 - p) / 0.18)
        lines = shot["card"]
        logo = shot.get("logo")
        first = self.f_logo if logo else self.f_title
        heights = [(first, 30 if logo else 24)] + [(self.f_text, 15)] * (len(lines) - 1)
        total = sum(h for _, h in heights) + (56 if logo else 0)
        y = (H - total) // 2
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        if logo:
            icon = d20_icon(40, 20)
            layer.alpha_composite(icon, ((W - 40) // 2, y))
            n = "20"
            nw = self.f_text.getlength(n)
            draw_text(ld, ((W - nw) / 2, y + 13), n, self.f_text, INK)
            y += 56
        for i, (line, (f, h)) in enumerate(zip(lines, heights)):
            if f.getlength(line) > W - 16:          # vertical cut: wrap long lines
                parts = wrap(line, f, W - 16)
            else:
                parts = [line]
            for part in parts:
                lw = f.getlength(part)
                draw_text(ld, ((W - lw) / 2, y), part, f, GOLD if i == 0 else WHITE, shadow=(0, 0, 0, 255))
                y += h
        if alpha < 1:
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * max(0.0, alpha))))
        img.alpha_composite(layer)
        return img.convert("RGB")

    # Vertical frame ----------------------------------------------------
    def vertical(self, world, overlay, panels, dialog, t, fade, focus, header: str) -> Image.Image:
        img = Image.new("RGBA", (V_W, V_H), (12, 16, 18, 255))
        d = ImageDraw.Draw(img)
        # Header
        title = "NAT 20 PIXELS"
        tw = self.f_title.getlength(title)
        draw_text(d, ((V_W - tw) / 2, 8), title, self.f_title, GOLD, shadow=(0, 0, 0, 255))
        hw = self.f_small.getlength(header)
        draw_text(d, ((V_W - hw) / 2, 34), header, self.f_small, WHITE)
        # Scene
        x0 = int(round(min(max(focus - V_W / 2, 0), W_W - V_W)))
        scene = world.crop((x0, 0, x0 + V_W, V_SCENE))
        scene.alpha_composite(overlay.crop((x0, 0, x0 + V_W, V_SCENE)))
        img.alpha_composite(scene, (0, V_TOP))
        if "dice" in panels:
            img.alpha_composite(panels["dice"], ((V_W - 216) // 2, V_TOP))
        if "hud" in panels:
            img.alpha_composite(panels["hud"], (V_W - 4 - panels["hud"].width, V_TOP + V_SCENE - 6 - panels["hud"].height))
        if "initiative" in panels:
            img.alpha_composite(panels["initiative"], (4, V_TOP + V_SCENE - 6 - panels["initiative"].height))
        d.line([(0, V_TOP), (V_W, V_TOP)], fill=BOX_EDGE)
        d.line([(0, V_TOP + V_SCENE), (V_W, V_TOP + V_SCENE)], fill=BOX_EDGE)
        # Dialogue, re-flowed for the narrow box
        if dialog is not None:
            self._dialog(img, dialog, t)
        if fade > 0:
            img.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, int(255 * min(1.0, fade)))))
        return img.convert("RGB")

    def _dialog(self, img: Image.Image, ds, t: float):
        d = ImageDraw.Draw(img)
        x0, y0 = 4, V_TOP + V_SCENE + 8
        bw = V_W - 8
        has_face = ds.kind == "say" and ds.faceset is not None
        tx = x0 + (52 if has_face else 10)
        width = x0 + bw - 8 - tx
        lines = wrap(ds.text, self.f_text, width)
        max_lines = 9
        lines = lines[:max_lines]
        bh = max(58, 20 + 12 * len(lines) + (0 if not ds.name else 4))
        y0 = V_TOP + V_SCENE + (V_H - V_TOP - V_SCENE - bh) // 2        # centred in the lower band
        d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=5, fill=BOX_FILL, outline=BOX_EDGE, width=2)
        d.rounded_rectangle((x0 + 2, y0 + 2, x0 + bw - 2, y0 + bh - 2), radius=4, outline=BOX_EDGE2)
        ty = y0 + 8
        if has_face:
            img.alpha_composite(ds.faceset, (x0 + 8, y0 + 10))
        if ds.kind == "say" and ds.name:
            draw_text(d, (tx, ty), ds.name, self.f_small, BOX_EDGE)
            ty += 12
        remaining = ds.visible_chars(t)
        color = INK if ds.kind == "say" else TEXT_INK
        # Visible characters are counted on the original wrap; re-count on ours.
        for line in lines:
            if remaining <= 0:
                break
            draw_text(d, (tx, ty), line[:remaining], self.f_text, color)
            remaining -= len(line)
            ty += 12
        if ds.done_typing(t) and int(t * 2.5) % 2 == 0:
            img.alpha_composite(self.arrow, (x0 + bw - 20, y0 + bh - 16))


# ----------------------------------------------------------------- build
class Encoder:
    def __init__(self, path: Path, size: tuple[int, int], fps: int, scale: int, preset: str, crf: int):
        self.path, self.size, self.fps = path, size, fps
        w, h = size
        self.cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                    "-r", str(fps), "-i", "-", "-vf", f"scale={w * scale}:{h * scale}:flags=neighbor",
                    "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", str(path)]
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE)
        self.n = 0
        self.stills: list[Image.Image] = []

    def write(self, frame: Image.Image, still_every: int):
        self.proc.stdin.write(frame.tobytes())
        if self.n % still_every == 0:
            self.stills.append(frame.copy())
        self.n += 1

    def close(self):
        self.proc.stdin.close()
        self.proc.wait()
        if self.proc.returncode != 0:
            raise RuntimeError("ffmpeg video encode failed")


def contact_sheet(stills: list[Image.Image], path: Path, cols: int):
    if not stills:
        return
    w, h = stills[0].size
    rows = math.ceil(len(stills) / cols)
    sheet = Image.new("RGB", (cols * w, rows * h), (0, 0, 0))
    for i, s in enumerate(stills):
        sheet.paste(s, ((i % cols) * w, (i // cols) * h))
    sheet.save(path)


def build(spec: dict, out_dir: Path, only: str | None, preview: bool, log=print) -> dict:
    assets = Assets()
    comp = Composer(assets)
    fps = 30
    scale, preset, crf = (2, "ultrafast", 28) if preview else (4, "medium", 18)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="pqc_trailer_"))
    formats = {}
    if only in (None, "wide"):
        formats["wide"] = Encoder(tmp / "wide.mp4", (W_W, W_H), fps, scale, preset, crf)
    if only in (None, "vertical"):
        formats["vertical"] = Encoder(tmp / "vertical.mp4", (V_W, V_H), fps, scale, preset, crf)
    audio = {k: [] for k in formats}          # trailer-time audio events per format
    t_out = {k: 0.0 for k in formats}
    still_every = fps                         # one still a second for the contact sheets
    t_start = time.time()

    def card(shot, formats_for):
        n = int(round(shot["dur"] * fps))
        for k in formats_for:
            enc = formats[k]
            for i in range(n):
                enc.write(comp.card(enc.size, shot, (i + 0.5) / n), still_every)
            t_out[k] += n / fps

    # Group episode windows by episode, in shot order (episodes are in order in the spec).
    shots = spec["shots"]
    i = 0
    while i < len(shots):
        shot = shots[i]
        if "card" in shot:
            card(shot, [k for k in formats if not (k == "vertical" and shot.get("wide_only"))])
            i += 1
            continue
        ep = shot["ep"]
        j = i
        while j < len(shots) and shots[j].get("ep") == ep:
            j += 1
        group = shots[i:j]
        eid = f"C01-E{ep:03d}"
        d = ROOT / "episodes" / eid
        tl = json.loads((d / "timeline.json").read_text())
        pk = json.loads((d / "packaging.json").read_text())
        header = f"Episode {ep} - {pk['title'].split('|')[0].strip()}"
        windows = [Window(s, i + k) for k, s in enumerate(group)]
        log(f"{eid}: {len(windows)} shot(s)")
        runner = ClipRunner(tl, assets, windows, spec.get("reading", {}))
        current, start_ep, start_out = None, 0.0, {}
        for w, t, (wide, world, overlay, panels, dialog, fade, focus) in runner.clips():
            if w is not current:
                # Carry over this window's sound effects when it ends (see below).
                current, start_ep = w, w.t0
                start_out = dict(t_out)
            fmts = [k for k in formats if not (k == "vertical" and w.shot.get("wide_only"))]
            for k in fmts:
                enc = formats[k]
                if k == "wide":
                    enc.write(wide, still_every)
                else:
                    enc.write(comp.vertical(world, overlay, panels, dialog, t, fade, focus, header), still_every)
                t_out[k] += 1 / fps
        # Sound effects and blips inside each window, shifted to trailer time.
        for w in windows:
            if w.t0 is None:
                raise SystemExit(f"{eid}: cue {w.cue} never started (shot {w.index})")
        # Recompute each window's output start: windows were written in order.
        for k in formats:
            pos = start_pos(k, shots, formats, fps, group, i)
            for w, p in zip(windows, pos):
                if p is None:
                    continue
                for e in runner.stage.audio:
                    if e["type"] in ("sfx", "blip") and w.t0 <= e["t"] < w.t0 + w.dur:
                        audio[k].append({**e, "t": p + (e["t"] - w.t0)})
        i = j

    # Music from the spec.
    results = {}
    for k, enc in formats.items():
        enc.close()
        duration = enc.n / fps
        events = list(audio[k])
        for m in spec.get("music", []):
            t = m["t"] if m["t"] >= 0 else duration + m["t"]
            events.append({"type": "music", "id": m["track"], "t": t, "fade_in": m.get("fade_in", 0.5),
                           "volume": m.get("volume", 0.55)})
        samples = mix(events, duration, assets)
        wav = tmp / f"{k}.wav"
        write_wav(wav, samples)
        final = out_dir / f"{spec['id']}_{k}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(enc.path), "-i", str(wav), "-c:v", "copy",
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", "-movflags", "+faststart", str(final)], check=True)
        sheet = out_dir / f"{spec['id']}_{k}_contact.png"
        contact_sheet(enc.stills, sheet, 8 if k == "wide" else 12)
        results[k] = {"out": str(final), "duration_s": round(duration, 2), "frames": enc.n,
                      "resolution": f"{enc.size[0] * scale}x{enc.size[1] * scale}", "contact_sheet": str(sheet)}
    shutil.rmtree(tmp, ignore_errors=True)
    results["render_seconds"] = round(time.time() - t_start, 1)
    log(json.dumps(results, indent=1))
    return results


def start_pos(fmt: str, shots: list[dict], formats, fps: int, group: list[dict], first: int) -> list[float | None]:
    """Trailer-time start of each shot in `group` for a format (None if the shot is skipped)."""
    t = 0.0
    out = []
    for idx, s in enumerate(shots):
        skip = fmt == "vertical" and s.get("wide_only")
        if first <= idx < first + len(group):
            out.append(None if skip else t)
        if not skip:
            t += round(s["dur"] * fps) / fps if "card" in s else s["dur"]
    return out



# ------------------------------------------------------------ thumbnails
def scene_frame(ep: int, cue: int, offset: float, assets: Assets, reading: dict | None = None):
    """The clean 480x270 scene `offset` seconds into a cue, plus the stage (for actor positions)."""
    d = ROOT / "episodes" / f"C01-E{ep:03d}"
    tl = json.loads((d / "timeline.json").read_text())
    if reading:
        tl = {**tl, "reading": {**tl.get("reading", {}), **reading}}
    r = Runner(tl, assets)
    frame = None
    for _ in r.frames(render=False):
        if len(r.cue_times) > cue and r.stage.t >= r.cue_times[cue] + offset:
            frame = r.stage.render(clean=True)
            break
    return frame or r.stage.render(clean=True), r.stage


def zoomed(frame: Image.Image, st, focus: str | None, size: tuple[int, int], scale: int = 4) -> Image.Image:
    """Crop a (size/scale) window around the focus actor and scale it up."""
    w, h = size[0] // scale, size[1] // scale
    fx, fy = W_W / 2, W_H / 2
    if focus and focus in st.actors:
        cx, cy = st._camera()
        fx, fy = (st.actors[focus].x - cx) * 2, (st.actors[focus].y - cy) * 2 - 10
    x0 = int(min(max(fx - w / 2, 0), W_W - w))
    y0 = int(min(max(fy - h / 2, 0), W_H - h))
    return frame.convert("RGBA").crop((x0, y0, x0 + w, y0 + h)).resize(size, Image.NEAREST)


def outline_text(d: ImageDraw.ImageDraw, xy, text, font, fill, step: int = 7):
    x, y = xy
    for dx in range(-step, step + 1, step):
        for dy in range(-step, step + 1, step):
            d.text((x + dx, y + dy), text, font=font, fill=(20, 27, 27))
    d.text((x, y), text, font=font, fill=fill)


def trailer_thumbnails(spec: dict, out_dir: Path, assets: Assets | None = None) -> list[Path]:
    """Two thumbnails: 1280x720 for the trailer, 1080x1920 for the Short."""
    from pqc.render import brand

    assets = assets or Assets()
    th = spec.get("thumbnail", {})
    party = th.get("faces", ["brannoc", "ilsevel", "tamsin", "oriel"])
    text = th.get("text", "EVERY ROLL IS REAL.")
    frame, st = scene_frame(th.get("ep", 9), th.get("cue", 75), th.get("offset", 0.9), assets, spec.get("reading"))
    gold = (255, 214, 102)
    out = []

    def faces_row(width_avail: int):
        fs = 6
        while 38 * fs * len(party) + 20 * (len(party) - 1) > width_avail:
            fs -= 1
        row = Image.new("RGBA", (38 * fs * len(party) + 20 * (len(party) - 1) + 16, 38 * fs + 16), (0, 0, 0, 0))
        x = 0
        for who in party:
            face = assets.actor(who).faceset.resize((38 * fs, 38 * fs), Image.NEAREST)
            card = Image.new("RGBA", (face.width + 16, face.height + 16), (20, 27, 27, 255))
            ImageDraw.Draw(card).rectangle((0, 0, card.width - 1, card.height - 1), outline=brand.MID, width=6)
            card.alpha_composite(face, (8, 8))
            row.alpha_composite(card, (x, 0))
            x += face.width + 20
        return row

    # 16:9 -------------------------------------------------------------
    img = zoomed(frame, st, th.get("focus", "brannoc"), (1280, 720))
    shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(shade)
    for y in range(200, 720):
        d.line([(0, y), (1280, y)], fill=(8, 10, 14, int(225 * (y - 200) / 520)))
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 1279, 719), outline=brand.MID, width=6)
    d.rectangle((6, 6, 1273, 713), outline=(20, 27, 27, 255), width=4)
    row = faces_row(1100)
    img.alpha_composite(row, ((1280 - row.width) // 2, 240))
    big = assets.font_at("title", 112)
    while d.textlength(text, font=big) > 1160:
        big = assets.font_at("title", big.size - 6)
    tw = d.textlength(text, font=big)
    outline_text(d, ((1280 - tw) / 2, 540), text, big, gold)
    mark = brand.d20_mark(assets, 2)
    small = assets.font_at("title", 36)
    label = th.get("label", "TRAILER")
    lw = d.textlength(label, font=small)
    d.rounded_rectangle((40, 40, 40 + mark.width + 24 + lw + 28, 40 + mark.height + 8), 14, fill=(20, 27, 27, 235),
                        outline=brand.MID, width=3)
    img.alpha_composite(mark, (52, 44))
    draw_text(d, (52 + mark.width + 16, 44 + (mark.height - 36) // 2), label, small, WHITE)
    word = brand.wordmark(assets, 2)
    d.rounded_rectangle((1280 - word.width - 72, 40, 1280 - 40, 48 + word.height + 8), 14, fill=(20, 27, 27, 235),
                        outline=brand.MID, width=3)
    img.alpha_composite(word, (1280 - word.width - 56, 52))
    p = out_dir / f"{spec['id']}_thumbnail_16x9.png"
    img.convert("RGB").save(p)
    out.append(p)

    # 9:16 -------------------------------------------------------------
    img = Image.new("RGBA", (1080, 1920), brand.BG)
    logo = brand.lockup(assets, stacked=True, scale=5)
    img.alpha_composite(logo, ((1080 - logo.width) // 2, 70))
    scene = zoomed(frame, st, th.get("focus", "brannoc"), (1080, 900))
    img.alpha_composite(scene, (0, 470))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 470, 1079, 1369), outline=brand.MID, width=6)
    row = faces_row(1000)
    img.alpha_composite(row, ((1080 - row.width) // 2, 1370 - row.height // 2))
    big = assets.font_at("title", 120)
    lines = text.split(" ", 2)
    lines = [" ".join(lines[:2]), " ".join(lines[2:])] if len(lines) > 2 else [text]
    y = 1370 + row.height // 2 + 50
    for line in lines:
        f = big
        while d.textlength(line, font=f) > 1000:
            f = assets.font_at("title", f.size - 6)
        outline_text(d, ((1080 - d.textlength(line, font=f)) / 2, y), line, f, gold)
        y += 126
    p = out_dir / f"{spec['id']}_thumbnail_9x16.png"
    img.convert("RGB").save(p)
    out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("out_dir")
    ap.add_argument("--only", choices=["wide", "vertical"])
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--thumbnails", action="store_true", help="only make the two thumbnails")
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    Path(a.out_dir).mkdir(parents=True, exist_ok=True)
    if a.thumbnails:
        for p in trailer_thumbnails(spec, Path(a.out_dir)):
            print(p)
        return 0
    build(spec, Path(a.out_dir), a.only, a.preview)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
