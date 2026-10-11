"""The Pit's thumbnails (1280x720): huge pixel portraits, few words, one question.

One template for the whole season, so the channel page reads as a series:
side colours split diagonally, the fighters' faces at 8x, a big VS (or the
format's word), and at most four words of text.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from ..render.assets import Assets
from ..render.tilemap import TileMap
from . import season as SE
from . import show as S

TW, TH = 1280, 720
INK = (12, 16, 18, 255)


def _font(assets: Assets, size: int):
    return assets.font_at("small", size)


def outlined(d, xy, text, f, fill, stroke=8, outline=INK):
    x, y = xy
    d.fontmode = "1"
    for dx in range(-stroke, stroke + 1, 2):
        for dy in range(-stroke, stroke + 1, 2):
            if dx * dx + dy * dy <= stroke * stroke:
                d.text((x + dx, y + dy), text, font=f, fill=outline)
    d.text((x, y), text, font=f, fill=fill)


def center_text(d, cx, y, text, f, fill, stroke=8):
    outlined(d, (int(cx - f.getlength(text) / 2), y), text, f, fill, stroke)


def fit(assets, text, width, sizes=(128, 96, 80, 64, 48)):
    for s in sizes:
        f = _font(assets, s)
        if f.getlength(text) <= width:
            return f
    return _font(assets, sizes[-1])


def background(assets: Assets, ca, cb, split=True) -> Image.Image:
    tm = TileMap.load(SE.MAP, assets)
    g = tm.ground.convert("RGBA")
    # The sand ring, scaled up 4x and darkened.
    crop = g.crop((40, 40, 40 + 320, 40 + 180)).resize((TW, TH), Image.NEAREST)
    img = Image.alpha_composite(crop, Image.new("RGBA", (TW, TH), (10, 12, 14, 200)))
    if split:
        over = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        d.polygon([(0, 0), (TW // 2 + 90, 0), (TW // 2 - 90, TH), (0, TH)], fill=ca[:3] + (110,))
        d.polygon([(TW // 2 + 90, 0), (TW, 0), (TW, TH), (TW // 2 - 90, TH)], fill=cb[:3] + (110,))
        d.line([(TW // 2 + 90, 0), (TW // 2 - 90, TH)], fill=(255, 255, 255, 230), width=10)
        img = Image.alpha_composite(img, over)
    return img


def portrait(assets: Assets, sprite: str, scale: int, flip=False) -> Image.Image:
    f = assets.actor(sprite).faceset
    if f is None:
        f = S._icon(assets, sprite, 2)
    if flip:
        f = f.transpose(Image.FLIP_LEFT_RIGHT)
    f = f.resize((f.width * scale, f.height * scale), Image.NEAREST)
    # A dark outline so the face pops off any background.
    out = Image.new("RGBA", (f.width + 24, f.height + 24), (0, 0, 0, 0))
    mask = f.getchannel("A").point(lambda v: 255 if v > 0 else 0)
    blk = Image.new("RGBA", f.size, INK)
    for dx in range(0, 25, 6):
        for dy in range(0, 25, 6):
            out.paste(blk, (dx, dy), mask)
    out.alpha_composite(f, (12, 12))
    return out


def badge(d, assets, cx, cy, text, fill=(242, 201, 76, 255), ink=INK):
    f = _font(assets, 48)
    w = f.getlength(text)
    d.rounded_rectangle((cx - w / 2 - 22, cy - 34, cx + w / 2 + 22, cy + 34), radius=14, fill=fill, outline=ink, width=6)
    d.fontmode = "1"
    d.text((cx - w / 2, cy - 24), text, font=f, fill=ink)


def render(season: dict, n: int, results: dict, out: Path, assets: Assets) -> str:
    ep = SE.episode(season, n)
    res = results[n]
    kind = ep["kind"]
    seg = res["segments"][0]
    lines = ep.get("thumb_text")
    if kind in ("duel", "crown_final") or (kind == "crown_semis"):
        if kind == "duel":
            a, b = ep["a"], ep["b"]
        else:
            a, b = seg["a"][0]["monster"], seg["b"][0]["monster"]
        img = background(assets, S.A_COL, S.B_COL)
        pa, pb = portrait(assets, a, 9), portrait(assets, b, 9, flip=True)
        img.alpha_composite(pa, (70, TH - pa.height - 30))
        img.alpha_composite(pb, (TW - pb.width - 70, TH - pb.height - 30))
        d = ImageDraw.Draw(img)
        if kind == "duel":
            na, nb = ep.get("thumb_names", [ep["hook"][0], ep["hook"][2]])
            fa, fb = fit(assets, na, 560, (96, 80, 64)), fit(assets, nb, 560, (96, 80, 64))
            outlined(d, (40, 30), na, fa, S.A_COL)
            outlined(d, (TW - 40 - int(fb.getlength(nb)), 30), nb, fb, S.B_COL)
            center_text(d, TW / 2, TH // 2 - 80, "VS", _font(assets, 128), (255, 255, 255, 255), 10)
            badge(d, assets, TW / 2, TH - 150, ep.get("thumb_badge", "WHO WINS?"))
        else:
            title = "THE FINAL" if kind == "crown_final" else "SEMIFINALS"
            center_text(d, TW / 2, 24, title, _font(assets, 96), S.GOLD, 10)
            center_text(d, TW / 2, TH // 2 - 60, "VS", _font(assets, 128), (255, 255, 255, 255), 10)
            badge(d, assets, TW / 2, TH - 90, "BRONZE CROWN")
    elif kind == "how_many":
        img = background(assets, S.A_COL, S.B_COL)
        ps = portrait(assets, ep["star"], 10)
        img.alpha_composite(ps, (40, TH - ps.height - 20))
        mini = portrait(assets, ep.get("minion_sprite", ep["minion"]), 4, flip=True)
        for i in range(9):
            x = TW - 40 - (3 - i % 3) * (mini.width - 8)
            y = 150 + (i // 3) * (mini.height - 12)
            img.alpha_composite(mini, (x, y))
        d = ImageDraw.Draw(img)
        center_text(d, TW / 2, 24, "HOW MANY?", _font(assets, 128), S.GOLD, 10)
        badge(d, assets, TW * 3 // 4 - 20, TH - 110, ep.get("thumb_badge", f"VS 1 {ep['hook'][2].strip('?').split()[-1]}"))
    else:  # rumble
        img = background(assets, (90, 40, 120, 255), (40, 20, 60, 255), split=False)
        fs = seg["fighters"]
        k = len(fs)
        scale = 5 if k > 5 else 6
        ps = [portrait(assets, f["sprite"], scale) for f in fs]
        cols = 4 if k > 5 else k
        pw = ps[0].width - 10
        x0 = TW // 2 - cols * pw // 2
        for i, p in enumerate(ps):
            r, c = divmod(i, cols)
            img.alpha_composite(p, (x0 + c * pw, 200 + r * (p.height - 30)))
        d = ImageDraw.Draw(img)
        center_text(d, TW / 2, 24, ep.get("thumb_title", "LAST ONE STANDING"), fit(assets, ep.get("thumb_title", "LAST ONE STANDING"), TW - 80, (96, 80, 64)), S.GOLD, 10)
        badge(d, assets, TW / 2, TH - 100, ep.get("thumb_badge", f"{k} ENTER. 1 LEAVES."))
    # Series mark, bottom centre.
    d = ImageDraw.Draw(img)
    f = _font(assets, 32)
    label = f"THE PIT  #{n:02d}"
    w = f.getlength(label)
    d.rounded_rectangle((TW / 2 - w / 2 - 14, TH - 52, TW / 2 + w / 2 + 14, TH - 10), radius=8, fill=INK)
    d.fontmode = "1"
    d.text((TW / 2 - w / 2, TH - 47), label, font=f, fill=S.GOLD)
    img.convert("RGB").save(out)
    return str(out)
