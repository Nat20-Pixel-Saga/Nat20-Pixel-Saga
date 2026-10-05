#!/usr/bin/env python3
"""A contact sheet of an episode for human review: one frame per scene, per
on-screen roll and per fight beat, without rendering the whole video.

    python scripts/contact_sheet.py C01-E001            # -> episodes/C01-E001/contact_sheet.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def moments(tl: dict, cue_times: list[float], limit: int = 15) -> list[tuple[float, str]]:
    out = []
    cues = tl["cues"]
    for ch in tl.get("chapters", []):
        if ch["cue"] < len(cues):
            out.append((cue_times[ch["cue"]] + 6.0, ch["title"]))
    for i, c in enumerate(cues):
        if c["op"] == "roll":
            out.append((cue_times[i] + 1.3, c.get("label", "roll")))
        elif c["op"] == "dm_intro":
            out.append((cue_times[i] + 12.0, "Storyteller"))
        elif c["op"] in ("battle_start", "battle_end"):
            out.append((cue_times[i] + 1.0, c["op"].replace("_", " ")))
    attacks = [i for i, c in enumerate(cues) if c["op"] in ("battle_attack", "battle_cast")]
    for i in attacks[:: max(1, len(attacks) // 4)]:
        out.append((cue_times[i] + 0.9, cues[i].get("label", "")))
    out = sorted(set(out))
    if len(out) > limit:
        step = len(out) / limit
        out = [out[int(k * step)] for k in range(limit)]
    return out


def contact_sheet(episode_id: str, out: Path | None = None, cols: int = 3) -> Path:
    from PIL import Image, ImageDraw

    from pqc.render.assets import Assets
    from pqc.render.timeline import Runner
    d = ROOT / "episodes" / episode_id
    tl = json.loads((d / "timeline.json").read_text())
    assets = Assets()
    probe = Runner(tl, assets)
    probe.duration()
    picks = moments(tl, probe.cue_times)
    r = Runner(tl, assets)
    fps = r.stage.fps
    frames, j = [], 0
    for i, _ in enumerate(r.frames(render=False)):
        while j < len(picks) and i >= int(picks[j][0] * fps):
            frames.append((picks[j], r.stage.render().convert("RGB")))
            j += 1
        if j >= len(picks):
            break
    w, h = 480, 270
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, (h + 16) * rows), (16, 12, 24))
    dr = ImageDraw.Draw(sheet)
    for k, ((t, label), im) in enumerate(frames):
        x, y = (k % cols) * w, (k // cols) * (h + 16)
        sheet.paste(im, (x, y + 16))
        dr.text((x + 4, y + 2), f"{int(t // 60)}:{int(t % 60):02d}  {label}"[:70], fill=(240, 230, 200),
                font=assets.font("small"))
    out = out or d / "contact_sheet.png"
    sheet.save(out)
    return out


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "C01-E001"
    print(contact_sheet(f"C01-E{int(arg):03d}" if arg.isdigit() else arg))
