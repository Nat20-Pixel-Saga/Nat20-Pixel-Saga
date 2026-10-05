"""Render a timeline to MP4: frames piped to ffmpeg, audio mixed, then muxed.

The canvas is 480x270; ffmpeg scales 4x with nearest-neighbour to 1920x1080
so pixels stay crisp.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .assets import Assets
from .audio import mix, write_wav
from .timeline import Runner
from .ui import H, W


def render(timeline: dict, out_path: str | Path, assets: Assets | None = None, scale: int = 4,
           crf: int = 18, preset: str = "medium", stills: list[float] | None = None,
           stills_dir: str | Path | None = None, log=print) -> dict:
    assets = assets or Assets()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    runner = Runner(timeline, assets)
    fps = runner.stage.fps
    tmp = Path(tempfile.mkdtemp(prefix="pqc_render_"))
    video_tmp = tmp / "video.mp4"
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
        "-i", "-", "-vf", f"scale={W * scale}:{H * scale}:flags=neighbor", "-c:v", "libx264", "-preset", preset,
        "-crf", str(crf), "-pix_fmt", "yuv420p", str(video_tmp),
    ]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    still_frames = {int(round(s * fps)) for s in (stills or [])}
    saved = []
    n = 0
    try:
        for frame in runner.frames():
            proc.stdin.write(frame.tobytes())
            if n in still_frames and stills_dir:
                p = Path(stills_dir) / f"{out_path.stem}_{n / fps:06.2f}s.png"
                p.parent.mkdir(parents=True, exist_ok=True)
                frame.resize((W * 2, H * 2), 0).save(p)
                saved.append(str(p))
            n += 1
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg video encode failed")
    duration = n / fps
    samples = mix(runner.stage.audio, duration, assets)
    wav = tmp / "audio.wav"
    write_wav(wav, samples)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video_tmp), "-i", str(wav), "-c:v", "copy",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    info = {"out": str(out_path), "frames": n, "fps": fps, "duration_s": round(duration, 2),
            "resolution": f"{W * scale}x{H * scale}", "render_seconds": round(time.time() - t0, 1),
            "audio_events": len(runner.stage.audio), "stills": saved}
    log(json.dumps(info))
    return info


def render_frames(frames, size: tuple[int, int], out_path: str | Path, audio_events: list[dict],
                  assets: Assets | None = None, fps: int = 30, scale: int = 4, crf: int = 18,
                  preset: str = "medium") -> dict:
    """Encode an iterable of RGB frames (any canvas size) plus mixed audio events to MP4.
    Same codec settings as `render`, so the result concatenates cleanly with episodes."""
    assets = assets or Assets()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    tmp = Path(tempfile.mkdtemp(prefix="pqc_render_"))
    video_tmp = tmp / "video.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-", "-vf", f"scale={w * scale}:{h * scale}:flags=neighbor", "-c:v", "libx264", "-preset", preset,
           "-crf", str(crf), "-pix_fmt", "yuv420p", str(video_tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = 0
    try:
        for frame in frames:
            proc.stdin.write(frame.convert("RGB").tobytes())
            n += 1
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg video encode failed")
    duration = n / fps
    wav = tmp / "audio.wav"
    write_wav(wav, mix(audio_events, duration, assets))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video_tmp), "-i", str(wav), "-c:v", "copy",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"out": str(out_path), "frames": n, "duration_s": round(duration, 2), "resolution": f"{w * scale}x{h * scale}"}
