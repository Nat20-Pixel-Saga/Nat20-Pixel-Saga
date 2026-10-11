"""Turn a simulated episode into files: the 16:9 video, its Shorts, its thumbnail, the roll log.

    files = produce(season, n, out_dir)       # everything for episode n
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

from ..render.assets import Assets
from ..render.audio import mix, write_wav
from ..render.ui import H, W
from . import season as SE
from . import show as S


def encode(frames, size, out_path: Path, audio_events: list[dict], assets: Assets, fps: int = 30, scale: int = 4,
           crf: int = 18, preset: str = "medium", stills: dict | None = None) -> dict:
    """Frames (PIL, canvas size) + audio events -> MP4, nearest-neighbour upscaled.
    ``stills``: {frame index: png path} to save on the way."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    tmp = Path(tempfile.mkdtemp(prefix="pit_"))
    vid = tmp / "v.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-", "-vf", f"scale={w * scale}:{h * scale}:flags=neighbor", "-c:v", "libx264", "-preset", preset,
           "-crf", str(crf), "-pix_fmt", "yuv420p", str(vid)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = 0
    try:
        for f in frames:
            f = f.convert("RGB")
            proc.stdin.write(f.tobytes())
            if stills and n in stills:
                f.resize((w * 2, h * 2), Image.NEAREST).save(stills[n])
            n += 1
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg video encode failed")
    dur = n / fps
    wav = tmp / "a.wav"
    write_wav(wav, mix(audio_events() if callable(audio_events) else audio_events, dur, assets))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(vid), "-i", str(wav), "-c:v", "copy",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"out": str(out_path), "frames": n, "duration_s": round(dur, 2)}


def dry_run(timeline: dict, assets: Assets):
    """Run a timeline without drawing: cue start times and total length."""
    S.install()
    r = S.ShowRunner(timeline, assets)
    for _ in r.frames(render=False):
        pass
    return r.cue_times, r.stage.t


def chapters(timeline: dict, times: list[float]) -> list[tuple[float, str]]:
    out = [(0.0, "The matchup")]
    seen = set()
    for t, c in zip(times, timeline["cues"]):
        meta = c.get("meta") or {}
        mk = meta.get("mark")
        label = None
        if c["op"] == "show_bout":
            label = c.get("chapter") or c["title"].title()
        elif mk == "result" and ("result", meta.get("seg")) not in seen:
            label = "Result and stats" if meta.get("seg") is None else f"Semifinal {meta['seg'] + 1}: result"
            seen.add(("result", meta.get("seg")))
        elif mk == "road":
            label = "Road to the Crown"
        elif mk == "crown":
            label = "The champion"
        elif mk == "season2":
            label = "Season 2"
        elif mk == "end":
            label = "Next in the Pit"
        if label:
            out.append((t, label))
    # YouTube wants chapters at least 10 s apart.
    clean = [out[0]]
    for t, l in out[1:]:
        if t - clean[-1][0] >= 10:
            clean.append((t, l))
    return clean


def fmt_t(t: float) -> str:
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


def render_episode(timeline: dict, out: Path, assets: Assets, scale: int = 4, stills_at: list[float] | None = None,
                   preset: str = "medium", crf: int = 18) -> dict:
    S.install()
    runner = S.ShowRunner(timeline, assets)
    fps = runner.stage.fps
    stills = {}
    if stills_at:
        sd = out.parent / "stills"
        sd.mkdir(parents=True, exist_ok=True)
        stills = {int(round(s * fps)): sd / f"{out.stem}_{s:06.2f}s.png" for s in stills_at}
    t0 = time.time()
    info = encode(runner.frames(), (W, H), out, lambda: runner.stage.audio, assets, fps, scale, crf, preset, stills)
    info["render_s"] = round(time.time() - t0, 1)
    info["stills"] = [str(p) for p in stills.values()]
    return info


def roll_log(season: dict, n: int, res: dict) -> dict:
    ep = SE.episode(season, n)
    out = {"show": season["show"], "season": season["id"], "episode": n, "title": ep["title"], "seed": ep["seed"],
           "engine": "pqc rules engine, SRD 5.2.1 stat blocks (production/arena/s1.json lists every seed)",
           "verify": "Each bout's rolls replay from its seed: pqc.dice.Dice.verify_log(seed, rolls)", "segments": []}
    for seg in res["segments"]:
        s = {"kind": seg["kind"], "seed": seg["seed"], "bouts": []}
        for b in SE.bouts_of(seg):
            s["bouts"].append({"seed": b["seed"], "winner": b["winner"], "rounds": b["rounds"],
                               "fighters": [{k: f[k] for k in ("id", "monster", "name", "team")} for f in b["fighters"]],
                               "rolls": b["rolls"], "events": b["events"]})
        out["segments"].append(s)
    return out
