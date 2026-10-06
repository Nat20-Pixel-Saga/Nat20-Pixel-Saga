#!/usr/bin/env python3
"""Import the curated subset of third-party art packs into assets/thirdparty/.

The packs themselves are not in the repository (and can't be downloaded from the
build machines); download them by hand, unzip, and run this once. It writes small
sheets the renderer and the wiki can use, each with its licence beside it.

    python3 scripts/import_art.py \
        --kenney ~/Downloads/Roguelike_pack \
        --dcss "~/Downloads/Dungeon Crawl Stone Soup Full" \
        --painterly ~/Downloads/painterly-spell-icons-1 ~/Downloads/painterly-spell-icons-2 \
                    ~/Downloads/painterly-spell-icons-3 ~/Downloads/painterly-spell-icons-4

Packs (all checked October 2026):

* Kenney "Roguelike pack" (CC0) - https://kenney.nl/assets/roguelike-rpg-pack
  The whole sheet, moved onto a gap-free 16 px grid so any manifest rect works.
  Kenney art is flat; set "outline": true on its props to match Ninja Adventure.
* Dungeon Crawl Stone Soup tiles (CC0) - https://github.com/crawl/tiles,
  https://opengameart.org/content/dungeon-crawl-32x32-tiles-supplemental
  Animated fire and torch strips, close-up item art, creature art (32 px).
* Painterly Spell Icons by J. W. Bjerk (eleazzaar) (CC-BY 3.0, attribution required)
  https://opengameart.org/users/eleazzaar - one icon per SRD spell, 64 px.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "thirdparty"
INK = (20, 27, 27)          # Ninja Adventure's outline colour

# ------------------------------------------------------------------ DCSS
ITEMS = {   # id -> path inside the DCSS "Full" release
    "lantern_lit": "item/misc/misc_lamp_new.png", "lantern_dead": "item/misc/misc_lamp_inert.png",
    "crystal_orb": "item/misc/misc_crystal_new.png", "crystal_pendant": "item/amulet/crystal_white.png",
    "black_glass_pendant": "item/amulet/stone_2_blue.png", "rune_stone": "item/misc/misc_rune.png",
    "phial": "item/misc/misc_phial.png",
    "key": "item/misc/key.png", "mirror": "item/misc/mirror.png", "horn": "item/misc/misc_horn.png",
    "potion_healing": "item/potion/ruby_new.png", "potion_blue": "item/potion/brilliant_blue_new.png",
    "scroll": "item/scroll/scroll-brown.png", "book": "item/book/book_dog_eared.png",
    "wand": "item/wand/gem_bronze_new.png", "ring": "item/ring/agate.png", "gold": "item/gold/gold_pile_10.png",
    "bread": "item/food/bread_ration_new.png",
    "longsword": "item/weapon/long_sword_1_new.png", "shortsword": "item/weapon/short_sword_1_new.png",
    "dagger": "item/weapon/dagger_new.png", "mace": "item/weapon/mace_1_new.png",
    "warhammer": "item/weapon/war_hammer.png", "handaxe": "item/weapon/hand_axe_1_new.png",
    "spear": "item/weapon/spear.png", "quarterstaff": "item/weapon/quarterstaff_new.png",
    "shortbow": "item/weapon/ranged/bow_1.png", "longbow": "item/weapon/ranged/longbow.png",
    "crossbow": "item/weapon/ranged/crossbow_1.png", "shield": "item/armor/shields/large_shield_1_new.png",
    "leather_armor": "item/armor/torso/leather_armor_1.png", "chain_mail": "item/armor/torso/chain_mail_1.png",
}
CREATURES = {
    "goblin": "monster/goblin_new.png", "hobgoblin": "monster/hobgoblin_new.png", "kobold": "monster/kobold_new.png",
    "gnoll": "monster/gnoll_new.png", "orc": "monster/orc_new.png", "orc_warrior": "monster/orc_warrior_new.png",
    "ogre": "monster/ogre_new.png", "troll": "monster/troll.png", "hill_giant": "monster/hill_giant_new.png",
    "wolf": "monster/animals/wolf.png", "worg": "monster/animals/warg.png", "jackal": "monster/animals/jackal_new.png",
    "bear": "monster/animals/black_bear_new.png", "boar": "monster/animals/hog_new.png", "rat": "monster/animals/rat.png",
    "bat": "monster/animals/bat.png", "spider": "monster/animals/spider.png", "snake": "monster/animals/snake.png",
    "zombie": "monster/undead/zombies/zombie_small.png", "skeleton": "monster/undead/skeletons/skeleton_humanoid_small_new.png",
    "ghoul": "monster/undead/ghoul.png", "wight": "monster/undead/wight_new.png", "wraith": "monster/undead/wraith.png",
    "ghost": "monster/undead/ghost_new.png", "shadow": "monster/undead/shadow_new.png",
    "necromancer": "monster/necromancer_new.png", "bandit": "monster/human_new.png", "mage": "monster/wizard.png",
    "imp": "monster/demons/imp.png", "harpy": "monster/harpy.png", "griffon": "monster/griffon.png",
    "basilisk": "monster/animals/basilisk.png", "wyvern": "monster/dragons/wyvern_new.png",
    "centaur": "monster/centaur.png", "minotaur": "monster/minotaur.png", "manticore": "monster/manticore.png",
    "dryad": "monster/dryad.png", "satyr": "monster/satyr.png", "raven": "monster/raven.png",
    "dwarf": "monster/dwarf_new.png", "elf": "monster/elf_new.png", "halfling": "monster/halfling_new.png",
    "human": "monster/human_old.png",
}


def copy_text(src: Path, dst: Path) -> None:
    """Copy a licence file as UTF-8 (some packs ship Windows-1252 text)."""
    raw = src.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    dst.write_text(text.replace("\r\n", "\n"), encoding="utf-8")


def save_sheet(images: dict[str, Image.Image], cell: int, cols: int, out: Path, credit: str,
               colours: int = 0) -> None:
    ids = list(images)
    rows = (len(ids) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 0))
    for i, k in enumerate(ids):
        im = images[k]
        sheet.alpha_composite(im, ((i % cols) * cell + (cell - im.width) // 2, (i // cols) * cell + (cell - im.height) // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    if colours:                                  # painted art: a 256-colour palette keeps it small
        sheet = sheet.quantize(colours, method=Image.FASTOCTREE, dither=Image.FLOYDSTEINBERG)
    sheet.save(out.with_suffix(".png"), optimize=True)
    out.with_suffix(".json").write_text(json.dumps({"cell": cell, "cols": cols, "credit": credit, "ids": ids}, indent=1) + "\n")


def flame_frames(dcss: Path) -> list[Image.Image]:
    """The eight-frame flame of the Makhleb altar, lifted off its stone base (22x25 each)."""
    frames = []
    for i in range(1, 9):
        a = np.array(Image.open(dcss / f"dungeon/altars/altar_makhleb_flame_{i}.png").convert("RGBA"))[:25, 4:26].copy()
        rgb = a[:, :, :3].astype(int)
        grey = (np.ptp(rgb, axis=2) < 30) & (rgb.sum(2) > 150) & (rgb.sum(2) < 560)
        grey[:20] = False                               # the altar's stone (the flame's white core stays)
        a[grey] = 0
        op = a[:, :, 3] > 0
        warm = op & (rgb.sum(2) > 150)
        keep = warm.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            keep |= np.roll(np.roll(warm, dy, 0), dx, 1) & op   # its outline
        a[~keep] = 0
        below = np.zeros_like(warm)
        below[:-1] = warm[:-1] & ~(a[1:, :, 3] > 0)
        below[-1] = warm[-1]
        a[np.roll(below, 1, 0) & ~(a[:, :, 3] > 0)] = (*INK, 255)   # close the bottom edge
        frames.append(Image.fromarray(a, "RGBA"))
    return frames


def half(img: Image.Image, rim: bool = False) -> Image.Image:
    """Halve outlined pixel art: average each 2x2 block, snap it back to the sprite's own palette, and
    redraw the outline (and, for flames, the red rim inside it) so the small version stays crisp."""
    a = np.array(img.convert("RGBA")).astype(float)
    h, w = (a.shape[0] + 1) // 2 * 2, (a.shape[1] + 1) // 2 * 2
    p = np.zeros((h, w, 4))
    p[:a.shape[0], :a.shape[1]] = a
    b = p.reshape(h // 2, 2, w // 2, 2, 4).transpose(0, 2, 1, 3, 4).reshape(h // 2, w // 2, 4, 4)
    op = b[..., 3] > 0
    n = op.sum(-1)
    avg = (b[..., :3] * op[..., None]).sum(-2) / np.maximum(n, 1)[..., None]
    pal = np.unique(a[a[..., 3] > 0][:, :3], axis=0)
    out = np.zeros((h // 2, w // 2, 4), np.uint8)
    out[..., :3] = pal[((avg[:, :, None, :] - pal[None, None]) ** 2).sum(-1).argmin(-1)]
    out[..., 3] = np.where(n >= 2, 255, 0)

    def ring(mask):
        m = np.pad(mask, 1)
        return mask & ~(m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:])

    o = out[..., 3] > 0
    edge = ring(o)
    out[edge, :3] = INK
    if rim:
        red = pal[np.argmax(pal[:, 0] - pal[:, 1] - pal[:, 2] / 2)]
        upper = np.arange(out.shape[0])[:, None] < out.shape[0] * 0.75      # the base stays white-hot
        out[ring(o & ~edge) & upper, :3] = red
    return Image.fromarray(out, "RGBA")


def black_glass(img: Image.Image) -> Image.Image:
    """Turn the blue stone of a pendant into black glass that drinks the light (keeps its highlight)."""
    a = np.array(img.convert("RGBA")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    stone = (b > r + 40) & (b > g + 20) & (a[..., 3] > 0)
    lum = (r * 0.3 + g * 0.59 + b * 0.11)[stone]
    v = np.clip(lum * 0.55, 6, 255)
    a[stone, 0], a[stone, 1], a[stone, 2] = v * 0.9, v * 0.85, v * 1.15
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


def strip(frames: list[Image.Image]) -> Image.Image:
    w, h = frames[0].size
    s = Image.new("RGBA", (w * len(frames), h), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        s.alpha_composite(f, (i * w, 0))
    return s


def import_dcss(src: Path) -> None:
    out = OUT / "dcss"
    out.mkdir(parents=True, exist_ok=True)
    flames = flame_frames(src)
    strip(flames).save(out / "fire_tall.png", optimize=True)
    strip([half(f, rim=True) for f in flames]).save(out / "fire_small.png", optimize=True)
    strip([Image.open(src / f"effect/cloud_fire_{i}.png").convert("RGBA") for i in range(3)]).save(out / "fire_ground.png", optimize=True)
    torch = [Image.open(src / f"dungeon/wall/torches/torch_{i}.png").convert("RGBA") for i in range(1, 5)]
    strip([half(f) for f in torch]).save(out / "torch.png", optimize=True)          # 16 px: fits a wall tile
    items = {k: Image.open(src / p).convert("RGBA") for k, p in ITEMS.items()}
    items["black_glass_pendant"] = black_glass(items["black_glass_pendant"])
    save_sheet(items, 32, 8, out / "items",
               "Dungeon Crawl Stone Soup tiles, CC0")
    save_sheet({k: Image.open(src / p).convert("RGBA") for k, p in CREATURES.items()}, 32, 8, out / "creatures",
               "Dungeon Crawl Stone Soup tiles, CC0")
    copy_text(src / "LICENSE.txt", out / "LICENSE.txt")
    copy_text(src / "README.txt", out / "README.txt")                 # the artists' credits


# --------------------------------------------------------------- Kenney
def import_kenney(src: Path) -> None:
    sheet = Image.open(src / "Spritesheet" / "roguelikeSheet_transparent.png").convert("RGBA")
    cols, rows = (sheet.width + 1) // 17, (sheet.height + 1) // 17
    out = Image.new("RGBA", (cols * 16, rows * 16), (0, 0, 0, 0))
    for r in range(rows):
        for c in range(cols):
            out.paste(sheet.crop((c * 17, r * 17, c * 17 + 16, r * 17 + 16)), (c * 16, r * 16))
    d = OUT / "kenney_roguelike"
    d.mkdir(parents=True, exist_ok=True)
    out.save(d / "roguelike_16.png", optimize=True)
    copy_text(src / "License.txt", d / "License.txt")


# ------------------------------------------------------------- painterly
SPELL_ICONS = {   # SRD spell id -> icon file name (any of the four parts)
    "fire_bolt": "fireball-red-2", "produce_flame": "light-air-fire-2", "burning_hands": "needles-fire-2",
    "fireball": "explosion-orange-2", "scorching_ray": "fire-arrows-2", "flaming_sphere": "explosion-red-1",
    "ray_of_frost": "ice-sky-1", "ice_knife": "ice-blue-2", "shocking_grasp": "lighting-sky-1",
    "lightning_bolt": "lightning-blue-3", "witch_bolt": "lightning-magenta-1", "thunderwave": "air-burst-sky-2",
    "gust_of_wind": "wind-sky-2", "magic_missile": "fire-arrows-royal-2", "acid_splash": "fireball-acid-2",
    "poison_spray": "fog-acid-1", "chill_touch": "horror-eerie-1", "ray_of_sickness": "beam-acid-1",
    "sacred_flame": "light-royal-2", "guiding_bolt": "beam-sky-2", "spiritual_weapon": "slice-sky-1",
    "cure_wounds": "heal-jade-1", "healing_word": "heal-sky-2", "mass_healing_word": "heal-royal-3",
    "spare_the_dying": "heal-jade-3", "bless": "enchant-royal-1", "bane": "evil-eye-red-1",
    "guidance": "enchant-sky-2", "resistance": "protect-jade-1", "shield": "protect-sky-1",
    "shield_of_faith": "protect-royal-2", "mage_armor": "protect-blue-2", "sanctuary": "protect-sky-3",
    "protection_from_evil_and_good": "protect-orange-2", "light": "light-sky-1", "dancing_lights": "light-blue-2",
    "faerie_fire": "light-magenta-2", "darkness": "fog-blue-1", "fog_cloud": "fog-sky-2",
    "sleep": "fog-magenta-2", "charm_person": "link-royal-1", "hold_person": "link-blue-1",
    "command": "link-spirit-1", "hex": "evil-eye-eerie-1", "hunters_mark": "evil-eye-red-2",
    "detect_magic": "runes-royal-1", "identify": "runes-blue-2", "comprehend_languages": "runes-orange-1",
    "entangle": "vines-jade-1", "goodberry": "leaf-jade-1", "thorn_whip": "vines-acid-2",
    "shillelagh": "enchant-jade-2", "barkskin": "leaf-orange-3", "longstrider": "haste-sky-1",
    "expeditious_retreat": "haste-royal-1", "misty_step": "fog-water-air-2", "blur": "haste-royal-2",
    "invisibility": "fog-sky-3", "silence": "air-burst-air-1", "web": "shielding-spirit-2",
    "vicious_mockery": "horror-red-1", "dissonant_whispers": "horror-eerie-2", "inflict_wounds": "rip-magenta-2",
    "second_wind": "heal-royal-1", "potion_of_healing": "heal-jade-2", "_default": "enchant-orange-1",
}


def import_painterly(srcs: list[Path]) -> None:
    files = {}
    for s in srcs:
        for p in s.rglob("*.png"):
            if "__MACOSX" not in p.parts:
                files[p.stem] = p
    missing = sorted({v for v in SPELL_ICONS.values() if v not in files})
    if missing:
        raise SystemExit(f"icons not found: {missing}")
    icons = {k: Image.open(files[v]).convert("RGBA").resize((64, 64), Image.LANCZOS) for k, v in SPELL_ICONS.items()}
    d = OUT / "painterly"
    save_sheet(icons, 64, 8, d / "spell_icons", "Painterly Spell Icons by J. W. Bjerk (eleazzaar), CC-BY 3.0", colours=256)
    readme = next((p for s in srcs for p in s.rglob("README.txt") if "__MACOSX" not in p.parts), None)
    if readme:
        copy_text(readme, d / "README.txt")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kenney", type=Path)
    ap.add_argument("--dcss", type=Path)
    ap.add_argument("--painterly", type=Path, nargs="+")
    a = ap.parse_args()
    if a.kenney:
        import_kenney(a.kenney.expanduser())
    if a.dcss:
        import_dcss(a.dcss.expanduser())
    if a.painterly:
        import_painterly([p.expanduser() for p in a.painterly])
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            print(f"{p.relative_to(ROOT)}  {p.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
