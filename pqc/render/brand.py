"""The channel's logo and branding, drawn in code (original pixel art).

The mark is a pixel d20 seen face-on: a hexagon split into seven facets with
"20" on the centre face. The wordmark is "NAT 20 PIXELS" in Pixelify Sans.
Everything is drawn at 1x on a small grid and scaled with nearest-neighbour,
so it stays crisp at any size.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .assets import Assets
from .ui import GOLD, INK, WHITE, draw_text

GRID = 48
LIGHT = (252, 226, 122, 255)
MID = (242, 201, 76, 255)
DARK = (196, 146, 52, 255)
DEEP = (150, 104, 40, 255)
BG = (12, 16, 18, 255)
SUB = (195, 192, 214, 255)

# Hexagon (face-on d20) on the 48 grid.
TOP, UR, LR, BOT, LL, UL = (24, 1), (46, 13), (46, 35), (24, 47), (2, 35), (2, 13)
M_TOP, M_R, M_L = (24, 13), (35, 30), (13, 30)        # midpoints of the big inverted triangle
_LIGHT_EDGE = (255, 244, 200, 255)


def d20_mark(assets: Assets, scale: int = 2, face: str = "20", dim: bool = False) -> Image.Image:
    """The d20 mark at `scale` (48*scale px square), transparent background."""
    img = Image.new("RGBA", (GRID, GRID), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    light, mid, dark, deep = (LIGHT, MID, DARK, DEEP) if not dim else (
        (120, 116, 134, 255), (100, 96, 114, 255), (80, 76, 92, 255), (60, 56, 70, 255))
    d.polygon([TOP, UR, LR, BOT, LL, UL], fill=mid)
    d.polygon([TOP, UL, UR], fill=light)                 # top facet catches the light
    d.polygon([UR, LR, BOT], fill=deep)                  # right side in shadow
    d.polygon([UL, LL, BOT], fill=dark)
    d.polygon([UL, M_TOP, M_L], fill=mid)
    d.polygon([UR, M_TOP, M_R], fill=dark)
    d.polygon([BOT, M_L, M_R], fill=dark)
    d.polygon([M_TOP, M_R, M_L], fill=light)             # the face with the number
    for a, b in ((UL, UR), (UR, BOT), (BOT, UL), (M_TOP, M_R), (M_R, M_L), (M_L, M_TOP),
                 (TOP, M_TOP), (LR, M_R), (LL, M_L)):
        d.line([a, b], fill=INK, width=1)
    d.polygon([TOP, UR, LR, BOT, LL, UL], outline=INK)
    d.line([TOP, UL], fill=_LIGHT_EDGE if not dim else SUB, width=1)   # rim light
    d.line([(TOP[0], TOP[1] + 1), (UR[0] - 1, UR[1])], fill=_LIGHT_EDGE if not dim else SUB, width=1)
    d.polygon([TOP, UR, LR, BOT, LL, UL], outline=INK)
    f = assets.font_at("small", 10)
    tw = f.getlength(face)
    draw_text(d, ((GRID - tw) / 2, 19), face, f, INK)
    return img.resize((GRID * scale, GRID * scale), Image.NEAREST)


def wordmark(assets: Assets, scale: int = 2, size: int = 20) -> Image.Image:
    """'NAT 20 PIXELS': NAT 20 in gold, PIXELS in white, with an ink shadow."""
    f = assets.font_at("title", size)
    a, b = "NAT 20", " PIXELS"
    wa, wb = f.getlength(a), f.getlength(b)
    h = size + 6
    img = Image.new("RGBA", (int(wa + wb) + 3, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    draw_text(d, (0, 1), a, f, GOLD, shadow=INK)
    draw_text(d, (wa, 1), b, f, WHITE, shadow=INK)
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def lockup(assets: Assets, stacked: bool = True, scale: int = 2, tagline: str | None = None) -> Image.Image:
    """Mark + wordmark (+ optional tagline), transparent background, at 1x then scaled."""
    mark = d20_mark(assets, 1)
    word = wordmark(assets, 1)
    tag = None
    if tagline:
        f = assets.font("text")
        tw = int(f.getlength(tagline))
        tag = Image.new("RGBA", (tw + 2, 16), (0, 0, 0, 0))
        draw_text(ImageDraw.Draw(tag), (0, 0), tagline, f, SUB, shadow=INK)
    gap = 6
    if stacked:
        w = max(mark.width, word.width, tag.width if tag else 0)
        h = mark.height + gap + word.height + ((4 + tag.height) if tag else 0)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.alpha_composite(mark, ((w - mark.width) // 2, 0))
        img.alpha_composite(word, ((w - word.width) // 2, mark.height + gap))
        if tag:
            img.alpha_composite(tag, ((w - tag.width) // 2, mark.height + gap + word.height + 4))
    else:
        w = mark.width + gap + max(word.width, tag.width if tag else 0)
        h = max(mark.height, word.height + ((4 + tag.height) if tag else 0))
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.alpha_composite(mark, (0, (h - mark.height) // 2))
        ty = (h - word.height - ((4 + tag.height) if tag else 0)) // 2
        img.alpha_composite(word, (mark.width + gap, ty))
        if tag:
            img.alpha_composite(tag, (mark.width + gap, ty + word.height + 4))
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def on_background(img: Image.Image, size: tuple[int, int], margin: float = 0.12) -> Image.Image:
    """Centre a transparent image on the brand background, scaled by an integer to fit."""
    W, H = size
    s = max(1, int(min((W * (1 - margin)) // img.width, (H * (1 - margin)) // img.height)))
    big = img.resize((img.width * s, img.height * s), Image.NEAREST)
    out = Image.new("RGBA", size, BG)
    out.alpha_composite(big, ((W - big.width) // 2, (H - big.height) // 2))
    return out
