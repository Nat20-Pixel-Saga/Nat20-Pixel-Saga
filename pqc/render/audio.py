"""Mix the timeline's audio events into one stereo track (numpy + ffmpeg decode)."""
from __future__ import annotations

import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from .assets import Assets

SR = 44100


@lru_cache(maxsize=64)
def decode(path: str) -> np.ndarray:
    """Decode any audio file to float32 stereo at 44.1 kHz."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(out, dtype=np.float32).reshape(-1, 2).copy()


def blip(pitch: float, n: int, dur: float = 0.035, volume: float = 0.07) -> np.ndarray:
    """A short square-wave text blip (original, generated)."""
    k = int(SR * dur)
    t = np.arange(k) / SR
    f = pitch * 2 * (1.0 + 0.03 * ((n % 3) - 1))
    wave_ = np.sign(np.sin(2 * np.pi * f * t)).astype(np.float32)
    env = np.minimum(1.0, (k - np.arange(k)) / (k * 0.6)).astype(np.float32)
    mono = wave_ * env * volume
    return np.stack([mono, mono], axis=1)


def _envelope(n: int, fade_in: int, fade_out: int) -> np.ndarray:
    env = np.ones(n, dtype=np.float32)
    if fade_in > 0:
        env[: min(fade_in, n)] = np.linspace(0, 1, min(fade_in, n), dtype=np.float32)
    if fade_out > 0 and n > 0:
        m = min(fade_out, n)
        env[n - m:] *= np.linspace(1, 0, m, dtype=np.float32)
    return env


def mix(events: list[dict], duration: float, assets: Assets, sfx_volume: float = 0.8) -> np.ndarray:
    n_total = int(duration * SR) + 1
    out = np.zeros((n_total, 2), dtype=np.float32)
    events = sorted(events, key=lambda e: e["t"])

    # Music: each start runs until the next music start or stop (with fades).
    music = [e for e in events if e["type"] in ("music", "music_stop")]
    for i, e in enumerate(music):
        if e["type"] != "music":
            continue
        start = int(e["t"] * SR)
        nxt = next((m for m in music[i + 1:]), None)
        end = int(nxt["t"] * SR) if nxt else n_total
        fade_out = int((nxt.get("fade_out", 0.4) if nxt else 1.0) * SR)
        end = min(n_total, end + (fade_out if nxt and nxt["type"] == "music_stop" else int(0.3 * SR)))
        length = max(0, end - start)
        if length == 0:
            continue
        track = decode(str(assets.music_path(e["id"])))
        reps = int(np.ceil(length / len(track)))
        seg = np.tile(track, (reps, 1))[:length]
        env = _envelope(length, int(e.get("fade_in", 0.5) * SR), fade_out if nxt else int(1.0 * SR))
        out[start:start + length] += seg * env[:, None] * e.get("volume", 0.55)

    for e in events:
        s = int(e["t"] * SR)
        if s >= n_total:
            continue
        if e["type"] == "sfx":
            clip = decode(str(assets.sfx_path(e["id"]))) * e.get("volume", 1.0) * sfx_volume
        elif e["type"] == "blip":
            clip = blip(e.get("pitch", 260), s)
        else:
            continue
        m = min(len(clip), n_total - s)
        out[s:s + m] += clip[:m]

    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0.98:
        out = np.tanh(out * 1.1) / np.tanh(1.1 * peak) * 0.98
    return out


def write_wav(path: str | Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
