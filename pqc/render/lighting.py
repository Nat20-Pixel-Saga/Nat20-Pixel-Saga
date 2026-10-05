"""Time-of-day tint, lantern glows and the Unlight (desaturation)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Ambient light multiplier per channel and how much point lights restore.
PRESETS = {
    "day": {"ambient": (1.0, 1.0, 1.0), "glow": 0.0},
    "morning": {"ambient": (1.0, 0.97, 0.92), "glow": 0.05},
    "dusk": {"ambient": (0.96, 0.80, 0.80), "glow": 0.35},
    "evening": {"ambient": (0.62, 0.55, 0.72), "glow": 0.6},
    "night": {"ambient": (0.30, 0.34, 0.52), "glow": 1.0},
}
WARM = np.array([255, 196, 120], dtype=np.float32)


@dataclass
class Light:
    x: float
    y: float
    radius: float
    intensity: float = 1.0


@dataclass
class UnlightZone:
    x: float
    y: float
    radius: float
    strength: float = 1.0


def flicker(t: float, key: str, state: str) -> float:
    k = (sum(map(ord, key)) % 97) / 7.0
    if state == "dead":
        return 0.0
    if state == "flicker":
        v = 0.55 + 0.45 * math.sin(t * 23 + k) * math.sin(t * 7.3 + 2 * k)
        return max(0.0, v if (int(t * 9 + k) % 5) else 0.1)
    return 0.92 + 0.08 * math.sin(t * 6.1 + k)


def apply(frame: np.ndarray, preset: str, lights: list[Light], zones: list[UnlightZone],
          blend: float = 1.0) -> np.ndarray:
    """Light an RGB uint8 frame (H, W, 3). ``blend`` fades the preset in."""
    p = PRESETS[preset]
    h, w, _ = frame.shape
    img = frame.astype(np.float32)
    ambient = np.array(p["ambient"], dtype=np.float32)
    ambient = 1.0 - (1.0 - ambient) * blend
    if lights and p["glow"] > 0:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        mask = np.zeros((h, w), dtype=np.float32)
        for li in lights:
            if li.intensity <= 0:
                continue
            d2 = (xx - li.x) ** 2 + (yy - li.y) ** 2
            m = np.clip(1.0 - np.sqrt(d2) / max(li.radius, 1.0), 0.0, 1.0) ** 1.6 * li.intensity
            mask = np.maximum(mask, m)
        mask *= p["glow"] * blend
        mult = ambient[None, None, :] + (1.0 - ambient[None, None, :]) * mask[..., None]
        img = img * mult + WARM[None, None, :] * (mask[..., None] * 0.18)
    else:
        img = img * ambient[None, None, :]
    if zones:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        z = np.zeros((h, w), dtype=np.float32)
        for zo in zones:
            d = np.sqrt((xx - zo.x) ** 2 + (yy - zo.y) ** 2)
            z = np.maximum(z, np.clip((zo.radius - d) / max(zo.radius * 0.35, 1.0), 0.0, 1.0) * zo.strength)
        lum = (img @ np.array([0.299, 0.587, 0.114], dtype=np.float32))[..., None]
        grey = lum * np.array([0.92, 0.93, 0.98], dtype=np.float32) * 0.82
        img = img * (1 - z[..., None]) + grey * z[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)
