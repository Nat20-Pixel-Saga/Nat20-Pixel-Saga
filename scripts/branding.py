#!/usr/bin/env python3
"""Render the channel's branding: logo files, the common intro and the outro.

    python3 scripts/branding.py out/brand            # everything
    python3 scripts/branding.py out/brand --preview  # quick, low quality

Writes:
  logo_mark.png         the d20 mark, transparent, 384x384
  logo_stacked.png      mark over the wordmark, transparent (for thumbnails, the wiki)
  logo_wide.png         mark beside the wordmark with the tagline, transparent
  avatar_800.png        YouTube channel picture (800x800, mark on the dark background)
  banner_2560x1440.png  YouTube banner; the logo sits inside the 1546x423 safe area
  watermark_150.png     YouTube video watermark (150x150, transparent)
  intro_16x9.mp4 / intro_9x16.mp4    4.2 s: the die drops, lands on a 20, the name appears
  outro_16x9.mp4 / outro_9x16.mp4    3.0 s: logo and "New episode every weekday."

scripts/release_episodes.py puts the intro and outro on every episode video (one
encode, see pqc.render.video.render's `pre`/`post`); the chapter times in each
episode's packaging already allow for the intro.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc.render import brand  # noqa: E402
from pqc.render.assets import Assets  # noqa: E402
from pqc.render.ui import GOLD, INK, WHITE, draw_text  # noqa: E402
from pqc.render.video import render_frames  # noqa: E402

FPS = 30
SIZES = {"16x9": (480, 270), "9x16": (270, 480)}


def ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


def ease_in(p: float) -> float:
    return p * p


# ------------------------------------------------------------------ intro
def intro_frames(assets: Assets, size: tuple[int, int], dur: float = brand.INTRO_S):
    W, H = size
    rnd = random.Random(20)
    faces = {n: brand.d20_mark(assets, 2, face=str(n)) for n in range(1, 21)}
    word = brand.wordmark(assets, 2)
    f_tag = assets.font("text")
    tagline = "Every roll is real."
    mark_h = faces[20].height
    gap = 12
    block_h = mark_h + gap + word.height + 6 + 16
    top = (H - block_h) // 2
    mark_y = top
    word_y = top + mark_h + gap
    tag_y = word_y + word.height + 6
    land = 1.05          # when the die hits
    lock = 1.5           # when it settles on 20
    n = int(round(dur * FPS))
    particles = [(rnd.uniform(0, 2 * math.pi), rnd.uniform(40, 90), rnd.uniform(0.45, 0.8), rnd.choice([2, 3, 4]))
                 for _ in range(14)]
    for i in range(n):
        t = i / FPS
        img = Image.new("RGBA", size, brand.BG)
        d = ImageDraw.Draw(img)
        # The die: falls in, bounces once, then settles.
        if t < 0.2:
            y = None
        elif t < land:
            p = ease_in((t - 0.2) / (land - 0.2))
            y = -mark_h + (mark_y + 6 + mark_h) * p
        elif t < land + 0.3:
            p = (t - land) / 0.3
            y = mark_y + 6 - 10 * math.sin(p * math.pi)
        else:
            y = mark_y
        if y is not None:
            if t < lock:
                face = faces[1 + (int(t * 24) * 7 + i) % 20]
                shake = int(2 * math.sin(t * 60)) if t < land else 0
            else:
                face, shake = faces[20], 0
            img.alpha_composite(face, ((W - face.width) // 2 + shake, int(y)))
        # Burst of gold pixels when the 20 locks in.
        if lock <= t < lock + 0.8:
            age = t - lock
            cx, cy = W // 2, mark_y + mark_h // 2
            for ang, dist, life, sz in particles:
                if age < life:
                    p = ease_out(age / life)
                    px, py = cx + math.cos(ang) * dist * p, cy + math.sin(ang) * dist * p
                    col = GOLD if (age / life) < 0.6 else brand.DARK
                    d.rectangle((px, py, px + sz, py + sz), fill=col)
        if lock <= t < lock + 0.1:
            img.alpha_composite(Image.new("RGBA", size, (255, 255, 255, 140)))
        # Wordmark slides up and fades in; tagline follows.
        if t >= lock + 0.15:
            p = min(1.0, (t - lock - 0.15) / 0.45)
            layer = Image.new("RGBA", size, (0, 0, 0, 0))
            layer.alpha_composite(word, ((W - word.width) // 2, int(word_y + 10 * (1 - ease_out(p)))))
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * p)))
            img.alpha_composite(layer)
        if t >= lock + 0.7:
            shown = tagline[: int((t - lock - 0.7) * 40)]
            tw = f_tag.getlength(tagline)
            draw_text(d, ((W - tw) / 2, tag_y), shown, f_tag, brand.SUB, shadow=INK)
        if t > dur - 0.5:
            a = (t - (dur - 0.5)) / 0.5
            img.alpha_composite(Image.new("RGBA", size, (0, 0, 0, int(255 * a))))
        yield img


def intro_audio() -> list[dict]:
    return [{"type": "sfx", "id": "dice_roll", "t": 0.25, "volume": 0.7},
            {"type": "sfx", "id": "dice_land", "t": 1.05, "volume": 0.7},
            {"type": "sfx", "id": "nat20", "t": 1.5, "volume": 0.6},
            {"type": "music", "id": "theme", "t": 1.55, "fade_in": 0.2, "volume": 0.32}]


# ------------------------------------------------------------------ outro
def outro_frames(assets: Assets, size: tuple[int, int], dur: float = brand.OUTRO_S):
    W, H = size
    logo = brand.lockup(assets, stacked=True, scale=2, tagline="New episode every weekday.")
    f = assets.font("small")
    line2 = "Every roll is real. Seeded dice, shown on screen."
    n = int(round(dur * FPS))
    for i in range(n):
        t = i / FPS
        img = Image.new("RGBA", size, brand.BG)
        d = ImageDraw.Draw(img)
        y = (H - logo.height - 20) // 2
        img.alpha_composite(logo, ((W - logo.width) // 2, y))
        lw = f.getlength(line2)
        if lw > W - 16:
            line2a, line2b = "Every roll is real.", "Seeded dice, shown on screen."
            for k, s in enumerate((line2a, line2b)):
                draw_text(d, ((W - f.getlength(s)) / 2, y + logo.height + 10 + 12 * k), s, f, WHITE)
        else:
            draw_text(d, ((W - lw) / 2, y + logo.height + 10), line2, f, WHITE)
        a = 1.0
        if t < 0.35:
            a = t / 0.35
        elif t > dur - 0.6:
            a = (dur - t) / 0.6
        if a < 1:
            img.alpha_composite(Image.new("RGBA", size, (0, 0, 0, int(255 * (1 - a)))))
        yield img


def bumpers(assets: Assets, size: tuple[int, int] = (480, 270)):
    """(intro, outro) as (frames, audio events) pairs, for pqc.render.video.render(pre=, post=)."""
    return ((list(intro_frames(assets, size)), intro_audio()), (list(outro_frames(assets, size)), outro_audio()))


def outro_audio() -> list[dict]:
    return [{"type": "music", "id": "theme", "t": 0.0, "fade_in": 0.3, "volume": 0.35}]


# ------------------------------------------------------------------ files
def logo_files(assets: Assets, out: Path):
    mark = brand.d20_mark(assets, 8)
    mark.save(out / "logo_mark.png")
    brand.lockup(assets, stacked=True, scale=4).save(out / "logo_stacked.png")
    brand.lockup(assets, stacked=False, scale=4, tagline="Every roll is real.").save(out / "logo_wide.png")
    brand.on_background(brand.d20_mark(assets, 1), (800, 800), margin=0.2).convert("RGB").save(out / "avatar_800.png")
    wm = Image.new("RGBA", (150, 150), (0, 0, 0, 0))
    m3 = brand.d20_mark(assets, 3)
    wm.alpha_composite(m3, ((150 - m3.width) // 2, (150 - m3.height) // 2))
    wm.save(out / "watermark_150.png")
    # Banner: 2560x1440, with everything that matters inside the central 1546x423.
    banner = Image.new("RGBA", (2560, 1440), brand.BG)
    d = ImageDraw.Draw(banner)
    rnd = random.Random(7)
    scatter = Image.new("RGBA", banner.size, (0, 0, 0, 0))
    for _ in range(90):                                    # faint scatter of dim dice in the background
        x, y = rnd.randrange(0, 2560, 8), rnd.randrange(0, 1440, 8)
        if 400 < x < 2160 and 440 < y < 1000:
            continue
        s = rnd.choice([1, 1, 2])
        scatter.alpha_composite(brand.d20_mark(assets, s, face="", dim=True), (x, y))
    scatter.putalpha(scatter.getchannel("A").point(lambda v: v * 2 // 5))
    banner.alpha_composite(scatter)
    lock = brand.lockup(assets, stacked=False, scale=1, tagline="A pixel-art fantasy story, played by 5e rules.")
    s = min((1546 * 0.9) // lock.width, (423 * 0.9) // lock.height)
    lock = lock.resize((int(lock.width * s), int(lock.height * s)), Image.NEAREST)
    banner.alpha_composite(lock, ((2560 - lock.width) // 2, (1440 - lock.height) // 2))
    banner.convert("RGB").save(out / "banner_2560x1440.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--only", choices=["logos", "intro", "outro"])
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    assets = Assets()
    scale, preset, crf = (2, "ultrafast", 28) if a.preview else (4, "medium", 18)
    if a.only in (None, "logos"):
        logo_files(assets, out)
        print("logos written")
    for name, size in SIZES.items():
        if a.only in (None, "intro"):
            print(render_frames(intro_frames(assets, size), size, out / f"intro_{name}.mp4", intro_audio(), assets,
                                FPS, scale, crf, preset))
        if a.only in (None, "outro"):
            print(render_frames(outro_frames(assets, size), size, out / f"outro_{name}.mp4", outro_audio(), assets,
                                FPS, scale, crf, preset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
