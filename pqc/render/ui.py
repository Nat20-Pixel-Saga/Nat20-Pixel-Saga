"""UI layer, drawn at native 480x270 on top of the 2x-scaled world."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from .assets import Assets

W, H = 480, 270
INK = (20, 27, 27, 255)
PAPER = (242, 234, 241, 255)
GOLD = (242, 201, 76, 255)
WHITE = (244, 242, 250, 255)
RED = (209, 75, 52, 255)
GREEN = (116, 163, 52, 255)
GREY = (138, 134, 163, 255)


# ------------------------------------------------------------------ text
def wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            trial = (cur + " " + w).strip()
            if font.getlength(trial) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def draw_text(d: ImageDraw.ImageDraw, xy, text, font, fill, shadow=None):
    d.fontmode = "1"
    if shadow:
        d.text((xy[0] + 1, xy[1] + 1), text, font=font, fill=shadow)
    d.text(xy, text, font=font, fill=fill)


def stretch_h(img: Image.Image, width: int, left: int, right: int) -> Image.Image:
    """3-slice horizontal stretch (nearest neighbour)."""
    mid = img.crop((left, 0, img.width - right, img.height))
    out = Image.new("RGBA", (width, img.height), (0, 0, 0, 0))
    out.paste(img.crop((0, 0, left, img.height)), (0, 0))
    out.paste(mid.resize((width - left - right, img.height), Image.NEAREST), (left, 0))
    out.paste(img.crop((img.width - right, 0, img.width, img.height)), (width - right, 0))
    return out


# --------------------------------------------------------------- dialog
@dataclass
class DialogState:
    kind: str  # "say" | "narrate"
    speaker: str | None
    name: str | None
    text: str
    lines: list[str]
    t0: float
    cps: float
    faceset: Image.Image | None = None
    total_chars: int = 0

    def visible_chars(self, t: float) -> int:
        return min(self.total_chars, int(max(0.0, t - self.t0) * self.cps))

    def done_typing(self, t: float) -> bool:
        return self.visible_chars(t) >= self.total_chars


class UI:
    BOX_X, BOX_Y, BOX_W = 4, 206, 472

    def __init__(self, assets: Assets):
        self.a = assets
        self.f_text = assets.font("text")
        self.f_small = assets.font("small")
        self.f_title = assets.font("title")
        self.f_num = assets.font_at("text", 13)
        self.f_pop = assets.font_at("text", 16)
        self.box_face = stretch_h(assets.ui("dialog_face"), self.BOX_W, 70, 10)
        self.box_plain = stretch_h(assets.ui("dialog_plain"), self.BOX_W, 20, 20)
        self.arrow = assets.ui("arrow")
        self.dialog: DialogState | None = None
        self.card: dict | None = None
        self.title: dict | None = None
        self.dice: list[dict] = []
        self.popups: list[dict] = []
        self.hud: dict | None = None
        self.banner: dict | None = None
        self.initiative: dict | None = None
        self.dm: dict | None = None

    # ---------------------------------------------------------- dialog
    def text_width(self, kind: str) -> int:
        return 236 if kind == "say" else self.BOX_W - 24

    def make_dialog(self, kind, speaker, name, text, t0, cps, faceset) -> DialogState:
        lines = wrap(text, self.f_text, self.text_width(kind) if (kind == "narrate" or faceset is not None) else self.BOX_W - 24)
        ds = DialogState(kind, speaker, name, text, lines, t0, cps, faceset)
        ds.total_chars = sum(len(l) for l in lines)
        return ds

    def draw_dialog(self, canvas: Image.Image, t: float):
        ds = self.dialog
        if not ds:
            return
        d = ImageDraw.Draw(canvas)
        x0, y0 = self.BOX_X, self.BOX_Y
        has_face = ds.kind == "say" and ds.faceset is not None
        if has_face:
            canvas.alpha_composite(self.box_face, (x0, y0))
            canvas.alpha_composite(ds.faceset, (x0 + 6, y0 + 14))
            tx, ty = x0 + 52, y0 + 14
            if ds.name:
                draw_text(d, (x0 + 8, y0 + 1), ds.name, self.f_small, WHITE)
        else:
            canvas.alpha_composite(self.box_plain, (x0, y0 - 2))
            tx, ty = x0 + 12, y0 + 8
            if ds.kind == "say" and ds.name:
                pass
        remaining = ds.visible_chars(t)
        color = INK if ds.kind == "say" else (60, 54, 67, 255)
        max_lines = 3 if has_face else 4
        for i, line in enumerate(ds.lines[:max_lines]):
            if remaining <= 0:
                break
            draw_text(d, (tx, ty + i * 12), line[:remaining], self.f_text, color)
            remaining -= len(line)
        if ds.done_typing(t) and int(t * 2.5) % 2 == 0:
            canvas.alpha_composite(self.arrow, (x0 + self.BOX_W - 20, y0 + 42))

    # ------------------------------------------------------------ cards
    def draw_card(self, canvas: Image.Image, t: float):
        c = self.card
        if not c:
            return
        p = (t - c["t0"]) / c["dur"]
        if p < 0 or p > 1:
            return
        alpha = min(1.0, p / 0.12, (1 - p) / 0.15)
        text = c["text"]
        tw = int(self.f_small.getlength(text))
        bw = tw + 28
        x = (W - bw) // 2
        y = int(6 - (1 - min(1.0, p / 0.12)) * 20)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle((x, y, x + bw, y + 18), radius=4, fill=(20, 27, 27, 220), outline=GOLD)
        draw_text(d, (x + 14, y + 4), text, self.f_small, WHITE)
        _fade(layer, alpha)
        canvas.alpha_composite(layer)

    def draw_title(self, canvas: Image.Image, t: float):
        c = self.title
        if not c:
            return
        p = (t - c["t0"]) / c["dur"]
        if p < 0 or p > 1:
            return
        alpha = min(1.0, p / 0.15, (1 - p) / 0.2)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, int(200 * alpha) if c.get("backdrop", True) else 0))
        d = ImageDraw.Draw(layer)
        y = 100
        for i, line in enumerate(c["lines"]):
            f = self.f_title if i == 0 else self.f_text
            lw = f.getlength(line)
            draw_text(d, ((W - lw) / 2, y), line, f, GOLD if i == 0 else WHITE, shadow=(0, 0, 0, 255))
            y += 30 if i == 0 else 16
        _fade(layer, alpha, keep_bg=True)
        canvas.alpha_composite(layer)

    def draw_banner(self, canvas: Image.Image, t: float):
        b = self.banner
        if not b or t > b["t0"] + b["dur"]:
            return
        d = ImageDraw.Draw(canvas)
        text = b["text"]
        tw = self.f_small.getlength(text)
        x, y = 8, 8
        d.rectangle((x, y, x + tw + 12, y + 14), fill=(20, 27, 27, 230))
        draw_text(d, (x + 6, y + 2), text, self.f_small, GOLD)

    # ------------------------------------------------------------- dice
    def draw_dice(self, canvas: Image.Image, t: float):
        self.dice = [dd for dd in self.dice if t <= dd["t0"] + dd["dur"]]
        for i, dd in enumerate(self.dice[-1:]):
            _draw_dice_tray(self, canvas, dd, t)

    # ----------------------------------------------------------- popups
    def draw_popups(self, canvas: Image.Image, t: float):
        d = ImageDraw.Draw(canvas)
        keep = []
        for p in self.popups:
            age = t - p["t0"]
            if age > p["dur"]:
                continue
            keep.append(p)
            if age < 0:
                continue
            y = p["y"] - min(age, 0.4) * 40 - age * 6
            f = self.f_title if p.get("big") else self.f_pop
            tw = f.getlength(p["text"])
            draw_text(d, (p["x"] - tw / 2, y), p["text"], f, p.get("color", WHITE), shadow=(20, 27, 27, 255))
        self.popups = keep

    # -------------------------------------------------------------- hud
    def draw_hud(self, canvas: Image.Image, t: float, members: list[dict]):
        if not members:
            return
        d = ImageDraw.Draw(canvas)
        x, y = W - 132, 6
        d.rounded_rectangle((x, y, x + 126, y + 6 + 13 * len(members)), radius=3, fill=(20, 27, 27, 210), outline=GREY)
        for i, m in enumerate(members):
            yy = y + 4 + i * 13
            draw_text(d, (x + 5, yy), m["name"][:9], self.f_small, WHITE if m["hp"] > 0 else GREY)
            frac = max(0.0, m["hp"] / max(1, m["max_hp"]))
            col = GREEN if frac > 0.5 else GOLD if frac > 0.2 else RED
            d.rectangle((x + 54, yy + 3, x + 98, yy + 7), fill=(59, 54, 67, 255))
            if frac > 0:
                d.rectangle((x + 54, yy + 3, x + 54 + int(44 * frac), yy + 7), fill=col)
            draw_text(d, (x + 102, yy - 2), f"{m['hp']}", self.f_text, WHITE)

    def draw_initiative(self, canvas: Image.Image, t: float):
        ini = self.initiative
        if not ini or not (ini["t0"] <= t <= ini["t0"] + ini["dur"]):
            return
        d = ImageDraw.Draw(canvas)
        rows = ini["order"]
        x, y = 8, 28
        h = 18 + 13 * len(rows)
        d.rounded_rectangle((x, y, x + 132, y + h), radius=3, fill=(20, 27, 27, 225), outline=GOLD)
        draw_text(d, (x + 6, y + 3), "Initiative", self.f_small, GOLD)
        for i, r in enumerate(rows):
            shown = t >= ini["t0"] + 0.15 * i
            if not shown:
                continue
            col = (166, 214, 92, 255) if r.get("team") == "party" else (236, 128, 116, 255)
            draw_text(d, (x + 8, y + 15 + 13 * i), f"{i + 1}. {r['name']}"[:16], self.f_text, col)
            tw = self.f_text.getlength(str(r["total"]))
            draw_text(d, (x + 124 - tw, y + 15 + 13 * i), str(r["total"]), self.f_text, WHITE)

    def draw_dm(self, canvas: Image.Image, t: float):
        dm = self.dm
        if not dm or not (dm["t0"] <= t <= dm["t0"] + dm["dur"]):
            return
        age = t - dm["t0"]
        alpha = min(1.0, age / 0.4, (dm["t0"] + dm["dur"] - t) / 0.5)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, int(150 * alpha)))
        d = ImageDraw.Draw(layer)
        x0, y0, x1, y1 = 44, 22, W - 44, H - 22
        d.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=(236, 222, 196, 245), outline=(150, 83, 64, 255), width=2)
        d.rounded_rectangle((x0 + 4, y0 + 4, x1 - 4, y1 - 4), radius=4, outline=(201, 160, 110, 255))
        draw_text(d, (x0 + 14, y0 + 10), "THE STORYTELLER", self.f_small, (150, 83, 64, 255))
        tw = self.f_title.getlength(dm["title"])
        draw_text(d, ((W - tw) / 2, y0 + 22), dm["title"], self.f_title, (90, 50, 40, 255))
        if dm.get("subtitle"):
            sw = self.f_small.getlength(dm["subtitle"])
            draw_text(d, ((W - sw) / 2, y0 + 46), dm["subtitle"], self.f_small, (120, 90, 70, 255))
        d.line([(x0 + 40, y0 + 60), (x1 - 40, y0 + 60)], fill=(201, 160, 110, 255))
        visible = int(max(0.0, age - 0.5) * dm["cps"])
        y = y0 + 68
        for line in dm["lines"]:
            if visible <= 0:
                break
            draw_text(d, (x0 + 18, y), line[:visible], self.f_text, (40, 34, 30, 255))
            visible -= len(line)
            y += 13
        if visible > 0 and int(t * 2.5) % 2 == 0:
            canvas_arrow = self.arrow
            layer.alpha_composite(canvas_arrow, (x1 - 22, y1 - 20))
        _fade(layer, alpha, keep_bg=True)
        canvas.alpha_composite(layer)

    def draw(self, canvas: Image.Image, t: float, hud_members: list[dict] | None = None):
        if hud_members:
            self.draw_hud(canvas, t, hud_members)
        self.draw_popups(canvas, t)
        self.draw_card(canvas, t)
        self.draw_banner(canvas, t)
        self.draw_initiative(canvas, t)
        self.draw_dice(canvas, t)
        self.draw_dialog(canvas, t)
        self.draw_dm(canvas, t)
        self.draw_title(canvas, t)


def _fade(layer: Image.Image, alpha: float, keep_bg: bool = False):
    if alpha >= 1:
        return
    a = layer.getchannel("A").point(lambda v: int(v * max(0.0, alpha)))
    layer.putalpha(a)


# ------------------------------------------------------------ dice tray
def d20_icon(size: int, face: int | str, fill=(242, 201, 76, 255), dim=False) -> Image.Image:
    """An original pixel d20: a hexagon with facet lines and the number."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = size / 2
    r = size / 2 - 1
    pts = [(c + r * math.cos(math.radians(a)), c + r * math.sin(math.radians(a))) for a in range(-90, 270, 60)]
    base = fill if not dim else (110, 104, 120, 255)
    d.polygon(pts, fill=base, outline=INK)
    tri = [pts[0], pts[2], pts[4]]
    d.polygon(tri, outline=(150, 83, 64, 255) if not dim else (80, 76, 90, 255))
    return img


def _draw_dice_tray(ui: UI, canvas: Image.Image, dd: dict, t: float):
    age = t - dd["t0"]
    if age < 0:
        return
    roll = dd["roll"]
    w_, h_ = 216, 48
    x = 116  # between the enemy side and the party HP panel
    y = int(6 - (1 - min(1.0, age / 0.15)) * 56)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((x, y, x + w_, y + h_), radius=4, fill=(20, 27, 27, 230), outline=GOLD)
    draw_text(d, (x + 7, y + 3), dd.get("label", "")[:44], ui.f_small, (195, 192, 214, 255))
    spin = dd.get("spin", 0.7)
    if roll.get("kind") == "d20":
        faces = (roll.get("rolls") or [roll.get("natural")])[:2]
        kept = roll.get("natural")
        dimmed_one = False
        for i, fv in enumerate(faces):
            if age < spin:
                shown, dim = (int(age * 30) * 7 + i * 5 + roll.get("index", 0)) % 20 + 1, False
            else:
                shown = fv
                dim = len(faces) > 1 and (fv != kept or (faces.count(kept) == 2 and dimmed_one is False and i == 1))
                dimmed_one = dimmed_one or dim
            ix, iy = x + 7 + i * 28, y + 17
            layer.alpha_composite(d20_icon(26, shown, dim=dim), (ix, iy))
            num = str(shown)
            nw = ui.f_num.getlength(num)
            draw_text(d, (ix + 13 - nw / 2, iy + 6), num, ui.f_num, INK)
        if age >= spin:
            col = WHITE
            if roll.get("success") is True:
                col = (166, 214, 92, 255)
            elif roll.get("success") is False:
                col = (236, 128, 116, 255)
            if roll.get("critical"):
                col = GOLD
            lx = x + 12 + 28 * len(faces)
            for i, part in enumerate(_split_line(dd.get("line") or "", ui.f_text, w_ - (lx - x) - 6)[:2]):
                draw_text(d, (lx, y + 18 + i * 12), part, ui.f_text, col)
    else:
        if age >= spin * 0.5:
            for i, part in enumerate(_split_line(dd.get("line") or roll.get("notation", ""), ui.f_text, w_ - 14)[:2]):
                draw_text(d, (x + 7, y + 18 + i * 12), part, ui.f_text, WHITE)
    canvas.alpha_composite(layer)


def _split_line(line: str, font, width: int) -> list[str]:
    return wrap(line, font, width)[:3]
