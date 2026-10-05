---
id: visual-audio-style
title: Visual and Audio Style Guide
status: canon
---

# Visual and Audio Style Guide

> **Amendment 1 (Phase 2, October 2026) — this section overrides §1–§4 and §7 where they differ.**
>
> - **Art source.** The show uses the CC0 *Ninja Adventure Asset Pack* (Pixel-boy & AAA) as its base art, music and SFX library, logged in `assets/manifest.json` and credited in `assets/CREDITS.md`. New art must match its style: 16×16 chibi sprites, 1 px dark outline (`#141b1b`), the pack's shared palette (`Palette.png`) plus the Lanternlight accents used in the recolours.
> - **Resolution.** Canvas 480×270, upscaled 4× (nearest neighbour) to 1920×1080. The world and battle layers are drawn at 240×135 and doubled (each tile = 32 canvas px, ~15×8 tiles visible); UI is drawn at native 480×270 for finer text.
> - **Characters.** 16×16 sprites with 4 directions × 4 walk frames, plus attack, jump, item and special poses. Party members are recoloured stand-ins until bespoke sprites exist: Brannoc ← Monk, Ilsevel ← SorcererOrange, Tamsin ← Villager5, Oriel ← Woman (palettes in the manifest).
> - **Portraits.** One 38×38 face portrait per character (from the pack). Emotions are shown with emote bubbles over the sprite until emotion portrait sets are made.
> - **Narrator window.** The pack's dialog box stretched to 472×58 at the bottom: portrait slot, name tab, three lines of Pixelify Sans 12 px; narration uses the plain box with four lines. Typewriter at 32 characters/second with square-wave blips pitched per speaker.
> - **Fonts.** Pixelify Sans (dialogue, numbers, dice lines) and Tiny5 (labels, names, titles), both OFL 1.1. Tiny5 is never used for digits that must be read at a glance.
> - **Battle screen.** Side view on a tiled arena: enemies left facing right, party right facing left, enemy HP bars over sprites, party HP panel top-right, dice tray top-centre. Downed party members lie on their side, greyed out.
> - **Dice tray.** An original pixel d20 (hexagon) spins for 0.7 s, lands on the logged face; advantage/disadvantage show both dice with the dropped one dimmed. The line reads like `ADV 18 + 5 = 23 vs AC 15 HIT`.
> - **Lighting.** Time-of-day presets (day, morning, dusk, evening, night) tint the scene; lit lanterns cast warm glows; dead lanterns can spawn an Unlight zone that desaturates the area around them.
> - **Audio.** Music, SFX and jingles from the pack (ids in the manifest). Final mix normalised to −16 LUFS integrated, −1.5 dBTP.

## Original guide (pre-Phase 2)


All art is **original**. Nothing may copy sprites, UI frames, fonts, music or creature designs from any existing game. The look is "16-bit handheld RPG" as a genre — warm, readable, chunky.

## 1. Canvas

- **Native resolution:** 480 × 270, upscaled 4× nearest-neighbour to 1920 × 1080. No sub-pixel movement, no rotation of sprites except 90° steps, no anti-aliasing.
- **Tiles:** 16 × 16 px. Visible map area: 30 × 12 tiles (480 × 192 px). The bottom 78 px hold the narrator window.
- **Frame rate:** render at 30 fps; sprites animate at 6–8 fps.

## 2. The palette — "Lanternlight 32"

Every asset uses only these 32 colours (plus full transparency). The asset validator rejects anything off-palette.

| # | Hex | Role | # | Hex | Role |
| --- | --- | --- | --- | --- | --- |
| 0 | `#0e0b16` | Outline / void | 16 | `#f2c94c` | Lantern gold |
| 1 | `#241f33` | Deep shadow | 17 | `#fff1b8` | Lantern glow |
| 2 | `#3d3754` | Night | 18 | `#e07a2f` | Fire |
| 3 | `#5d5878` | Stone dark | 19 | `#b8401f` | Ember |
| 4 | `#8a86a3` | Stone | 20 | `#7a1f2b` | Blood / Kesh crimson |
| 5 | `#c3c0d6` | Stone light | 21 | `#d9577a` | Rose |
| 6 | `#f4f2fa` | White | 22 | `#7e4fa3` | Quill violet |
| 7 | `#1f3b2d` | Forest deep | 23 | `#4b2f6b` | Thessin indigo |
| 8 | `#2f6b3f` | Forest | 24 | `#2b4c8c` | Ondrel blue |
| 9 | `#5aa04a` | Grass | 25 | `#4f8fd6` | Sky / frost |
| 10 | `#a6d65c` | Grass light | 26 | `#9fd8f0` | Ice / magic light |
| 11 | `#3b2a1e` | Wood dark | 27 | `#1f6f6b` | Sea deep |
| 12 | `#6b4a2f` | Wood | 28 | `#3fb5a3` | Sea / fey teal |
| 13 | `#a0703f` | Leather | 29 | `#c9b8a8` | Unlight grey |
| 14 | `#d9a066` | Sand / skin mid | 30 | `#8f8378` | Unlight dark |
| 15 | `#f0d0a8` | Skin light | 31 | `#e8e0d5` | Unlight pale |

**Unlight rule:** inside Unlight, the renderer remaps every colour to the nearest of 29–31 and 0–6, desaturating the scene. Spells cast inside Unlight also desaturate.

## 3. Sprites

| Kind | Size | Frames | Notes |
| --- | --- | --- | --- |
| Overworld characters | 16 × 24 | 4 directions × 3 walk frames | 1 px dark outline (colour 0) |
| Battle sprites (party, normal monsters) | 32 × 32 | idle ×2, attack ×3, cast ×3, hurt ×1, down ×1 | Side view, facing right (party) / left (enemies) |
| Large monsters | 48 × 48 or 64 × 64 | idle ×2, attack ×3, hurt ×1 | |
| Bosses | 64 × 64 to 96 × 96 | idle ×4, 2 attacks ×3, phase change | Hand touch-up required |
| Portraits | 48 × 48 | 6 emotions: neutral, happy, sad, angry, surprised, determined | Shown in narrator window |
| Spell effects | 16–64 px | see §5 | Generated from presets |

**Party signatures** (must be recognisable in silhouette):

- **Brannoc:** wide, short; tower-like shield (rounded rectangle), red cape (19), iron helm with cheek guards. Shield gains a brass rim at L5, an anvil emblem at L11, glows ember at L17.
- **Ilsevel:** tall, thin; blue robes (24/25), silver hair (5), staff with a floating crystal (26) that brightens as she levels; Pell on her shoulder in overworld.
- **Tamsin:** small; violet hooded cloak (22), two daggers, a scarf that streams when she moves.
- **Oriel:** medium; white tabard (6) over chain mail (4), gold holy symbol (16) of the Open Hand, a warhammer, freckles, short auburn hair (19).

## 4. UI

- **Narrator window:** 464 × 70 px at (8, 196). Background colour 1, 2 px border colour 16 with corner studs. Portrait at left (48 × 48, framed). Speaker name plate above the window's top-left edge.
- **Text:** original 8 × 8 bitmap font ("Wickfont") in colour 6; character names in colour 16. Typewriter speed 25 chars/s; blips per character (pitch per speaker).
- **Party HUD (top-left):** four mini portraits 16 × 16 with HP bars (green 9 → yellow 16 → red 20 as HP drops).
- **Dice tray:** slides in from the right; d20 sprite 24 × 24 spins 0.8 s; result line `d20 (14) + 5 = 19 vs AC 16 — HIT`. Natural 20 = gold flash (16/17) + sting; natural 1 = grey crack (29) + low thud. Advantage shows two dice, the kept one bright and the dropped one dim. Damage dice appear as a row of small dice under the result.
- **Location card:** top-centre banner for 2 s, "Brindle Cross — Night".
- **Battle transition:** horizontal blinds wipe in 0.5 s into a side-view battle backdrop matching the biome.

## 5. Spell effect grammar

Every spell is built from presets with parameters. The script references spells by SRD id; `data/spell_fx.json` (Phase 2) maps each id to a preset config.

| Preset | Shape | Parameters | Example spells |
| --- | --- | --- | --- |
| `projectile` | A sprite flies caster → target | colour, size, trail, arc, count | Fire Bolt, Magic Missile (count 3), Guiding Bolt |
| `beam` | Line from caster to target | colour, width, flicker | Ray of Frost, Lightning Bolt, Scorching Ray (multiple) |
| `cone` | Fan from caster | colour, length, particles | Burning Hands, Cone of Cold |
| `sphere` | Expanding circle at a point | colour, radius, ring count | Fireball, Thunderwave (cube variant), Spirit Guardians |
| `aura` | Glow around a creature | colour, pulse rate | Bless, Shield of Faith, Shield |
| `sparkle` | Particles rising from target | colour, count | Cure Wounds, Healing Word, Mass Cure Wounds |
| `pillar` | Column from sky | colour, width | Sacred Flame, Flame Strike, Sunbeam |
| `summon` | Smoke puff + sprite | colour, sprite id | Find Familiar, Animate Dead |
| `wall` | Line of tiles | colour, animation | Wall of Fire, Wall of Force |
| `screen` | Full-screen flash or tint | colour, duration | Power Word Kill, Wish, Meteor Swarm |

Colour defaults by damage type: fire 18/19, cold 25/26, lightning 26/6, thunder 5/4, acid 10, poison 8, necrotic 23/1, radiant 16/17, force 21/6, psychic 22, healing 16/17.

Higher-level spells look bigger, not different: an upcast Fireball uses a larger radius and an extra ring.

## 6. Biome tilesets

`meadow`, `forest`, `deep-forest`, `village`, `city`, `castle`, `swamp`, `ruin`, `crypt`, `beach`, `volcanic`, `port`, `ship`, `fey`, `court`, `mountain`, `snow`, `dwarf-hold`, `forge`, `cave`, `fungal`, `crystal`, `drowned`, `desert`, `oasis`, `palace`, `tomb`, `farmland`, `storm`, `astral`, `bone-light`, `infernal`, `divine`. Each tileset: 256 tiles max, with autotile edges for paths, water and cliffs. Each lantern on a map is an animated object (healthy / flickering / dead).

## 7. Audio

All music and SFX are original or royalty-free and chiptune (square, triangle, noise, sample channel).

| Cue | Use | Feel |
| --- | --- | --- |
| `theme` | Title card, finale | Hopeful, marching, lantern motif (rising fifth) |
| `town-*` | Each settlement | Cosy loops, biome instrumentation |
| `route-*` | Overworld travel | Mid-tempo, walking feel |
| `dungeon-*` | Dungeons | Sparse, echoing |
| `battle` | Normal fights | Fast, driving |
| `battle-boss` | Bosses | Same motif in minor key, heavier drums |
| `unlight` | Inside Unlight | All channels low-pass filtered, slowed 10% |
| `campfire` | Bond scenes | Solo lute-like triangle melody |
| `ysolde` | Ysolde's presence | The lantern motif inverted |
| `level-up` | Level-up | 3-second fanfare |
| `treasure` | Item found | 1.5-second jingle |
| `death` | PC at 0 HP | Music cuts; heartbeat SFX until stabilised |

SFX: sword swing, hit, miss (whoosh), crit (sting), spell charge, spell release per preset, heal chime, dice roll, dice land, nat-20 sting, nat-1 thud, footsteps per surface, door, chest, coin.
