"""YouTube packaging: chapters, full description, thumbnail.

The model writes the title, the hook and the tags (Haiku 4.5). Everything
factual is appended here so it is always right: chapter times measured from
the timeline, the seed and the dice-verification line, and the licence credits.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..state import ROOT

MIN_CHAPTER = 10.0  # YouTube: chapters must be at least 10 s long


def fmt_time(t: float) -> str:
    t = int(round(t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def chapters(timeline: dict, cue_times: list[float], duration: float) -> list[dict]:
    """Chapter list from the assembler's markers and the measured cue times.
    The first chapter starts at 0:00; short ones are merged into the previous one."""
    marks = []
    for ch in timeline.get("chapters", []):
        t = cue_times[ch["cue"]] if ch["cue"] < len(cue_times) else duration
        title = "Intro" if ch["title"] in ("Title", "Previously") and not marks else ch["title"]
        if marks and ch["title"] == "Title":
            continue
        marks.append({"t": t, "title": title})
    if not marks or marks[0]["t"] > 0:
        marks.insert(0, {"t": 0.0, "title": "Intro"})
    while len(marks) > 1 and marks[1]["t"] - marks[0]["t"] < MIN_CHAPTER:
        marks.pop(0)  # a title card alone is too short to be a chapter: the next one starts at 0:00
    marks[0]["t"] = 0.0
    out: list[dict] = []
    for i, m in enumerate(marks):
        end = marks[i + 1]["t"] if i + 1 < len(marks) else duration
        if out and (end - m["t"] < MIN_CHAPTER):
            continue  # too short: folds into the previous chapter
        out.append(m)
    return [{"time": fmt_time(m["t"]), "seconds": round(m["t"], 2), "title": m["title"]} for m in out]


def with_bumpers(chap: list[dict], intro: float, outro: float, duration: float) -> tuple[list[dict], float]:
    """Chapter times and length of the published video, which starts with the common intro and
    ends with the outro (scripts/release_episodes.py). The first chapter still starts at 0:00."""
    out = []
    for i, c in enumerate(chap):
        t = 0.0 if i == 0 else c["seconds"] + intro
        out.append({"time": fmt_time(t), "seconds": round(t, 2), "title": c["title"]})
    return out, duration + intro + outro


def credits_footer() -> str:
    text = (ROOT / "assets" / "CREDITS.md").read_text(encoding="utf-8")
    return text.split("## Suggested description footer", 1)[-1].replace("> ", "").strip()


def full_description(pk: dict, record: dict, chap: list[dict], wiki_url: str | None) -> str:
    parts = [pk["description"].strip(), ""]
    if len(chap) >= 3:
        parts += ["Chapters"] + [f"{c['time']} {c['title']}" for c in chap] + [""]
    parts += [f"Every roll in this episode is real: seed {record['seed']}, {len(record['rolls'])} rolls, "
              f"all logged and verifiable" + (f" at {wiki_url}/dice/" if wiki_url else " on the wiki") + "."]
    if wiki_url:
        parts += [f"Episode page and lore: {wiki_url}/episodes/{record['id'].lower()}/"]
    parts += ["", credits_footer()]
    return "\n".join(parts)[:5000]


def thumbnail_time(moment: str | None, timeline: dict, cue_times: list[float], plan: dict) -> float:
    """Time of the thumbnail frame: ``s3`` (two seconds into scene 3) or ``e1:4`` (fight action 4)."""
    cues = timeline["cues"]
    if moment and ":" in moment:
        _, n = moment.split(":", 1)
        k = 0
        for i, c in enumerate(cues):
            if c["op"] in ("battle_attack", "battle_cast"):
                k += 1
                if k == int(n):
                    return cue_times[i] + 0.9  # projectile/impact on screen, dice tray up
    if moment and moment.startswith("s"):
        names = {s["id"]: s["name"] for s in plan["scenes"]}
        for ch in timeline.get("chapters", []):
            if ch["title"] == names.get(moment):
                return cue_times[min(ch["cue"] + 1, len(cue_times) - 1)] + 4.0
    return cue_times[len(cue_times) // 2]


THUMB_SPECS = ROOT / "assets" / "thumbnails"


def thumbnail_spec(episode_id: str) -> dict:
    """Hand-tuned choices for an episode's thumbnail (assets/thumbnails/c01.json):
    ``text`` (overrides the packager's), ``faces`` (actor ids whose portraits are shown),
    ``focus`` (actor the scene zooms on) and ``t`` (frame time, overrides the moment)."""
    f = THUMB_SPECS / f"{episode_id[:3].lower()}.json"
    if not f.exists():
        return {}
    return json.loads(f.read_text()).get(episode_id, {})


def _split_title(d, text: str, font, width: int) -> list[str]:
    words = text.split()
    if d.textlength(text, font=font) <= width or len(words) < 2:
        return [text]
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        wa, wb = d.textlength(a, font=font), d.textlength(b, font=font)
        if wa <= width and wb <= width:
            score = abs(wa - wb)
            if best is None or score < best[0]:
                best = (score, [a, b])
    return best[1] if best else [text]


def render_thumbnail(timeline: dict, t: float, text: str, episode_label: str, out: Path, assets=None,
                     spec: dict | None = None) -> Path:
    """1280x720 thumbnail: the scene zoomed in on the moment, the episode's faces as big
    portraits on the right, two to four big words bottom-left, and the channel badge."""
    from PIL import Image, ImageDraw

    from ..render import brand
    from ..render.assets import Assets
    from ..render.timeline import Runner
    from ..render.ui import draw_text

    assets = assets or Assets()
    spec = spec or {}
    text = spec.get("text", text)
    if "t" in spec:
        t = float(spec["t"])
    r = Runner(timeline, assets)
    target = int(t * r.stage.fps)
    frame = None
    for i, _ in enumerate(r.frames(render=False)):
        if i >= target:
            frame = r.stage.render(clean=True)
            break
    if frame is None:
        frame = r.stage.render(clean=True)
    st = r.stage
    # Zoom: a 320x180 window of the 480x270 canvas around the focus, scaled 4x.
    fx, fy = 240, 135
    focus = spec.get("focus")
    if focus in st.actors and st.actors[focus].visible:
        cx, cy = st._camera()
        fx, fy = (st.actors[focus].x - cx) * 2, (st.actors[focus].y - cy) * 2 - 10
    x0 = int(min(max(fx - 160, 0), 480 - 320))
    y0 = int(min(max(fy - 90, 0), 270 - 180))
    img = frame.convert("RGBA").crop((x0, y0, x0 + 320, y0 + 180)).resize((1280, 720), Image.NEAREST)
    # Shade: darker to the bottom-left so the text reads, and a thin frame.
    shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(shade)
    for y in range(300, 720):
        d.line([(0, y), (1280, y)], fill=(8, 10, 14, int(215 * (y - 300) / 420)))
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 1279, 719), outline=brand.MID, width=6)
    d.rectangle((6, 6, 1273, 713), outline=(20, 27, 27, 255), width=4)
    # Portraits on the right.
    faces = spec.get("faces", [])
    px = 1280 - 60
    fs = 7
    for k, who in enumerate(reversed(faces)):
        try:
            face = assets.actor(who).faceset
        except Exception:
            face = None
        if face is None:
            continue
        big = face.resize((38 * fs, 38 * fs), Image.NEAREST)
        w = big.width
        px -= w
        py = 720 - w - 70 if len(faces) == 1 else 720 - w - 70 - (0 if k == 0 else 40)
        if k:
            px += 36
        card = Image.new("RGBA", (w + 16, w + 16), (20, 27, 27, 255))
        ImageDraw.Draw(card).rectangle((0, 0, w + 15, w + 15), outline=brand.MID, width=6)
        card.alpha_composite(big, (8, 8))
        img.alpha_composite(card, (px - 8, py - 8))
        px -= 24
    text_right = (px - 40) if faces else 1220
    # Title: up to two lines of big gold letters with an ink outline.
    words = text.upper()
    size = 132
    while True:
        big = assets.font_at("title", size)
        lines = _split_title(d, words, big, text_right - 60)
        if all(d.textlength(l, font=big) <= text_right - 60 for l in lines) or size <= 64:
            break
        size -= 8
    lh = int(size * 1.05)
    y = 720 - 60 - lh * len(lines)
    for line in lines:
        x = 60
        for dx in range(-7, 8, 7):
            for dy in range(-7, 8, 7):
                d.text((x + dx, y + dy), line, font=big, fill=(20, 27, 27))
        d.text((x, y), line, font=big, fill=(255, 214, 102))
        y += lh
    # Channel badge: the d20 mark and the episode number.
    mark = brand.d20_mark(assets, 2)
    small = assets.font_at("title", 36)
    label = episode_label.split("-")[-1].strip() if "EPISODE" in episode_label else episode_label
    lw = d.textlength(label, font=small)
    d.rounded_rectangle((40, 40, 40 + mark.width + 24 + lw + 28, 40 + mark.height + 8), 14, fill=(20, 27, 27, 235),
                        outline=brand.MID, width=3)
    img.alpha_composite(mark, (52, 44))
    draw_text(d, (52 + mark.width + 16, 44 + (mark.height - 36) // 2), label, small, (244, 242, 250, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out)
    return out
