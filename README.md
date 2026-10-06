# Nat 20 Pixels Saga

An AI-run, fifth-edition-compatible actual-play series told as a 16-bit pixel-art RPG: one 5–10 minute episode every weekday, one party of four, level 1 to level 20.

This repository holds **Phase 1 — Foundations** (canon, party, state format, rules engine), **Phase 2 — Renderer and art** (CC0 assets, tile maps, cutscene runner, on-map tactical battles, dice overlay, audio, 1080p encoding) and **Phase 3 — Pilot pipeline** (Claude planner/writer/continuity/wiki/packaging steps, episode assembly, the MkDocs wiki, and Episode 1 produced end to end).

## What's here

| Path | What it is |
| --- | --- |
| `bible/` | The series bible: world, cosmology, pantheon, gazetteer, factions, history, NPCs, ten campaign arcs, voice and visual style, rules of play. `00_series_bible.md` is the index. |
| `dossiers/` | One dossier per party member: backstory, personality, voice sheet with sample lines, hooks, secrets, relationships, growth arc, level 1–20 plan. |
| `state/party/*.json` | Level-1 character sheets (SRD 5.2). The engine owns these. |
| `state/world.json` | World state: clock, campaign/episode counters, bonds, factions, NPCs, quests, lanterns, story hooks. |
| `schemas/` | JSON Schemas (draft 2020-12) for characters, world, episodes, rolls, intents and monsters. |
| `data/` | Game data: weapons, armour, items, spells, monsters, class progression. Every file carries a `verified` flag (see below). |
| `pqc/` | The rules engine (Python 3.11+, standard library only). |
| `tests/` | Unit and fuzz tests (`unittest`; also run under `pytest`). |
| `scripts/demo_combat.py` | The Phase 1 gate: a full fight from JSON with every roll logged and replay-verified. |
| `pqc/render/` | The renderer: asset library, tile maps + autotiling, lighting, stage, UI, timeline runner, director, audio mixer, video encoder. |
| `assets/manifest.json` | Logical ids for every actor, recolour, prop, terrain, effect, spell effect, music track, sound, font and UI piece. |
| `assets/maps/`, `assets/timelines/` | Tile maps (`pqc/map@1`: `brindle_cross`, `lantern_road`) and timelines (`pqc/timeline@1`). |
| `production/` | Overnight production: queue, runbook, log, map previews. |
| `assets/CREDITS.md` | Asset licences and the credit line for video descriptions. |
| `scripts/fetch_assets.sh` | Fetches the CC0 art/audio pack and OFL fonts into `vendor/` (pinned, licence-checked). |
| `scripts/make_gate_scene.py` | The Phase 2 gate: engine fight → director → timeline → 1080p MP4. |
| `scripts/render_timeline.py` | Render any timeline JSON to MP4. |
| `pqc/pipeline/` | Phase 3: Claude client and cost ledger, context packs, prompts and model routing, plan validation and resolution, timeline assembly, continuity, wiki builder, YouTube packaging, the episode orchestrator. |
| `prompts/` | One prompt per step (planner, writer, continuity checker, wiki, packager, campaign planner). |
| `campaign/c01.json` | Campaign 1 beat file: 40 episodes with tags, maps, encounters, key rolls, hooks, milestones. |
| `fixtures/C01-E001/` | Recorded step outputs for Episode 1, replayed offline and in CI. |
| `episodes/<id>/` | The archive: plan, outcomes, script, continuity report, timeline, chapters, wiki facts, packaging, thumbnail, cost, state after, video. |
| `wiki/` | MkDocs site (`mkdocs.yml`, generated `docs/`, human-approved `data/public/`). |
| `scripts/run_episode.py` | Produce an episode (offline replay, live, or record). |
| `scripts/contact_sheet.py`, `scripts/cost_report.py` | Review sheet of an episode; cost projection from its ledger. |
| `scripts/youtube_upload.py`, `production/youtube.json` | Uploads released episodes to YouTube and schedules their premieres (`.github/workflows/youtube.yml`; setup in `production/YOUTUBE.md`). |
| `production/schedule.json`, `pqc/schedule.py` | The premiere schedule: one episode per weekday at 21:00 Paris from 12 October 2026. The wiki, the GitHub releases and the YouTube uploader all follow it, so an episode appears everywhere at once. |
| `scripts/trailer.py`, `assets/timelines/trailer_c01.json` | Cuts a trailer from the episodes' timelines in 16:9 and 9:16 (Shorts) at once. |
| `scripts/shorts.py`, `pqc/pipeline/highlight.py`, `assets/shorts/` | One YouTube Short per episode: the highlight is picked automatically (natural 20s and 1s, death saves, a hero going down, decisive checks) or hand-tuned, rendered vertical with a hook line and an end card, plus a cover; title and description come from the packaging step. Released with the episode, public the next day at 13:00 Paris. |
| `scripts/branding.py`, `pqc/render/brand.py`, `assets/brand/` | The channel logo (an original pixel d20), avatar, banner, watermark, and the common intro and outro in 16:9 and 9:16. |

## Quick start

```bash
scripts/fetch_assets.sh                      # once: CC0 art/audio pack + fonts into vendor/ (~112 MB)
python3 -m unittest discover -s tests        # or: pytest  (renderer tests skip if vendor/ is missing)
python3 scripts/demo_combat.py               # C1E1 tutorial fight, writes out/C01-E001.json
python3 scripts/make_gate_scene.py           # ~65 s test scene -> render_out/gate_test_scene.mp4 (1080p)
python3 scripts/make_gate_scene.py --scale 2 # quick 960x540 preview
python3 scripts/run_episode.py 1             # Episode 1 offline from fixtures (~2 s, no render)
python3 scripts/run_episode.py 1 --render full   # ... and the 1080p video (~9 min of video)
ANTHROPIC_API_KEY=... python3 scripts/run_episode.py 2 --live --commit   # the real thing
```

Requirements: Python 3.11+, Pillow, numpy, ffmpeg with libx264 and AAC.

## How the engine works

The golden rule: **the writer never decides a roll.**

1. A planner (Claude) proposes *intents* — `{"type": "attack", "attack": "longsword", "target": "goblin-1"}`.
2. `pqc.combat.Encounter.act()` checks the intent is legal, rolls every die with `pqc.dice.Dice`, applies SRD 5.2 rules and appends events.
3. The writer narrates from the event log; the renderer draws the dice overlay from the roll log.

```python
from pqc.dice import Dice
from pqc.combat import Encounter
from pqc.state import load_party, monster_from_data

party = load_party()
goblin = monster_from_data("goblin_warrior", "goblin-1", pos=(6, 4))
enc = Encounter([*party.values(), goblin], Dice("C01-E001-1"))
enc.start()
enc.legal_actions()          # the menu shown to the tactical model
enc.act({"type": "attack", "attack": "shortbow", "target": "goblin-1"})
enc.end_turn()
```

### Dice

- Seed per episode: `C<campaign>-E<episode>-<attempt>` (e.g. `C01-E001-1`).
- Each die = HMAC-SHA256(seed, draw counter) with rejection sampling; every draw's counter is logged, so `Dice.verify_log(seed, log)` can prove no roll was altered or reordered. Publish seeds and logs on the wiki.
- `RollRecord.overlay_text()` gives the on-screen line, e.g. `d20 (14) + 5 = 19 vs 16 — SUCCESS`.

### Rules implemented (SRD 5.2)

- Ability checks with skills, expertise, tools, passive scores, group checks, contests; saving throws with species traits (Dwarven Resilience, Brave, Fey Ancestry), Bless, auto-fail from conditions; Halfling Luck; Exhaustion (−2 per level); Heroic Inspiration flag.
- HP, temporary HP, resistance/vulnerability/immunity, unconsciousness at 0 HP, Death Saving Throws (natural 1 and 20), massive-damage death, stabilising (Medicine or *Spare the Dying*).
- Combat: initiative with tie-breaks (or a fixed order for planned surprise), action / bonus action / reaction / movement economy, grid distance, reach and range (long-range disadvantage, ranged-in-melee disadvantage), opportunity attacks, Disengage, Dash, Dodge, Help, Hide, standing from prone, critical hits (doubled dice, Champion expanded range), natural-1 misses, auto-crits on helpless targets.
- Conditions: blinded, frightened, poisoned, prone, restrained, paralyzed, stunned, unconscious, invisible and more as advantage/disadvantage sources.
- Weapon Mastery: Vex, Sap, Slow, Graze, Topple, Push (Nick and Cleave are listed but not automated yet).
- Features: Sneak Attack (advantage or adjacent ally), Savage Attacker, Second Wind, Action Surge, Cunning Action, Nimble Escape, Pack Tactics, multiattack, Undead Fortitude, Potent Cantrip, Disciple of Life, Arcane Recovery.
- Spells: attack, save (half / none), auto-hit, healing, buffs and utility, cantrip scaling, upcasting, the one-slot-spell-per-turn bonus-action rule, concentration (DC max(10, half damage), capped at 30), reactions (*Shield* when it turns a hit into a miss, including vs *Magic Missile*), free casts from Magic Initiate.
- Rests (short, long, Arcane Recovery), milestone levelling 1→20 with fixed HP, ASIs (with retroactive Con HP), spell-slot progression, subclass gates at level 3.
- The original **Unlight** rest rule (bible `10_rules_of_play.md` §6).

### Tactical model hook

`pqc.llm.build_turn_prompt()` turns the situation and the legal-action menu into a compact prompt; `parse_choice()` accepts only a valid menu number; `make_llm_policy(call_model)` falls back to the deterministic `pqc.ai.simple_policy` on any bad answer and logs a `policy_fallback` event. Phase 3 plugs in the API call.

## How the renderer works

1. **Timeline** (`assets/timelines/*.json`, schema `pqc/timeline@1`): an ordered list of cues — `scene`, `spawn`, `move`, `camera`, `say`, `narrate`, `emote`, `location_card`, `title`, `lantern`, `time_of_day`, `music`, `sfx`, `fade`, `roll`, and battle cues `battle_start`, `battle_attack`, `battle_cast`, `battle_faint`, `battle_revive`, `battle_end`. Cues block until finished unless they say `"wait": false`.
2. **Director** (`pqc/render/director.py`): turns an engine encounter result into battle cues, attaching the *logged* roll to every attack, spell and death save, so the dice on screen are the dice the engine rolled.
3. **Runner and stage**: each cue becomes a task; the stage composes the map (autotiled terrain, y-sorted props), actors, effects and lighting at 240×135, doubles it to 480×270, then draws the UI (narrator box with portrait and typewriter text, location cards, dice tray, HP panel, damage pop-ups).
4. **Encode**: frames are piped to ffmpeg and scaled 4× nearest-neighbour to 1920×1080 H.264; music, SFX and text blips are mixed with numpy and normalised to −16 LUFS.

A 65-second scene renders in about 40 seconds on a laptop-class CPU.

### Materials still wanted

The pack covers everything structurally; these would raise quality and are the best places to spend on art:

| Need | Why | Stand-in today |
| --- | --- | --- |
| Bespoke party sprites (dwarf, elf, halfling, human) | Recoloured pack characters don't read as their species | Monk, SorcererOrange, Villager5, Woman |
| Emotion portraits (6 per party member + key NPCs) | The bible's portrait emotions; now shown with emote bubbles | One portrait each |
| Top-down goblins, wolves, Skarrow with walk cycles | No goblins or wolves in the pack | GreenPig, DemonGreen, Beast2 (close-up art now exists, see below) |
| European-style houses | The pack's houses look Japanese | Pack houses; Kenney's gabled roofs, walls, doors and windows are in `assets/thirdparty/kenney_roguelike/` ready to be composed |
| Battle backdrops per biome | Arena is tiled from the map tileset | Tiled grass/dirt arena |
| An old Lamplighter way-marker stone (C1E6) | Should read as a Lamplighter road marker, not a gravestone | TilesetElement carved stele (`waymarker`); `item:rune_stone` for a close-up |
| Pell's single white feather | Too small to show at 16 px | Recoloured pack owl (`pell`) |
| A proper watermill (C1E8-9) | Composite of pack art | `watermill` (assets/sprites) |
| Royal soldiers (C1E10) | Soldiers are pack knights/fighters | `soldier`, `soldier_b`, `soldier_c` |

#### Covered by the packs added in October 2026

Kenney Roguelike (CC0), Dungeon Crawl Stone Soup tiles (CC0) and J. W. Bjerk's Painterly Spell Icons
(CC-BY 3.0), imported by `scripts/import_art.py` into `assets/thirdparty/` (see its README). Campaign 1
was re-rendered with them on 6 October 2026 (lantern posts in Brindle Cross, the Lantern Road and Fort Harrow;
the animated campfires in Thornpike Woods; the burning barn; banners, torches and tents at Fort Harrow):

| Need | Now available |
| --- | --- |
| Iron-and-glass lantern post | `lantern_post` (drawn for the show; switches to `lantern_post_dead` when a `lantern` cue puts it out) |
| Animated campfire | `campfire_lit` (pack fire ring + animated flame), `campfire_small` |
| Animated burning barn (C1E9) | `barn_ablaze` (pack barn + animated flames); fx `fire_tall`, `fire_small`, `fire_ground` |
| Fort Harrow dressing (C1E10) | `wall_banner`, `royal_banner` (+ blue, green), `wall_torch`, `standing_torch`, `army_tent`, `portcullis`, `gateway_open`, `double_door` |
| Interiors | `fireplace`, `fireplace_tall`, `candelabra`, `knight_statue`, `anvil`, `market_stall`, `signpost`, grave crosses, and everything else on the Kenney sheet |
| Faceted crystal, black-glass pendant | Close-up art `item:crystal_pendant`, `item:black_glass_pendant` (32 px, for cards) |
| Creature and item close-ups, spell icons | `Assets.art("creature:goblin")` (44 creatures), `art("item:lantern_lit")` (36 items), `spell_icon("fire_bolt")` (64 spells) |

#### Free sources checked (October 2026)

Licences read on each page. All are CC0 unless marked; none can be downloaded from this
project's build machines (itch.io, OpenGameArt and kenney.nl are blocked there), so download the zips by hand
and commit the files you use under `assets/` with a line in `assets/CREDITS.md`.

| Need | Best free source | Licence | Fit |
| --- | --- | --- | --- |
| Party sprites | [0x72 DungeonTileset II](https://0x72.itch.io/dungeontileset-ii) (dwarf, elf, knight, wizard) | CC0 | 16 px, idle + run, side-facing only: up/down walks must be drawn; no halfling (shrink the dwarf/human) |
| Party sprites, soldiers | [Shade, Puny Characters](https://merchant-shade.itch.io/16x16-puny-characters) | CC0 | 8 directions, full animation set; chibi proportions, a weaker style match |
| Goblins, zombie, sorceress | DungeonTileset II (goblin, zombie, orcs, ogre as goblin boss, necromancer) | CC0 | As above |
| Wolves | [Dog/Wolf spritesheet](https://opengameart.org/content/dogwolf-spritesheet) | CC0 | Side view only; no top-down CC0 wolf found: needs drawing |
| Portraits | Ninja Adventure facesets + hand-drawn expressions; [32x32 Portraits](https://opengameart.org/node/96477) | CC0 | No CC0 set with several emotions per fantasy character exists |
| Buildings, castle walls | [ArMM1998 Zelda-like tilesets](https://opengameart.org/content/zelda-like-tilesets-and-sprites); [Shade MiniWorld](https://opengameart.org/content/miniworld-sprites); [bart 16x16 castle tiles](https://opengameart.org/content/16x16-castle-tiles) (CC-BY 3.0: credit "bart") | CC0 / CC-BY | Zelda-like is the closest style match |
| Animated campfire | [crad Campfire Animation](https://opengameart.org/content/campfire-animation) | CC0 | 8 frames |
| Burning barn | [Reactorcore Fire & Smoke](https://opengameart.org/content/fire-smoke-animations) over the barn | CC0 | Animated overlay |
| Crystal, pendant | [AntumDeluge jewelry icons](https://opengameart.org/node/120756) | CC0 | 16/24/32 px gems and amulets to recolour |
| Not found free | Way-marker stone, watermill, white feather, battle backdrops | | Draw, or commission |

Rejected: haggisbytes and thepixelgame goblin packs ("no redistribution"), jeresikstus characters (no licence),
cobgoblin portraits (CC-BY-SA: share-alike), Kenney Tiny Town (CC0 but flat, unoutlined style).

## How an episode is made (Phase 3)

```
campaign beat ─► PLAN (Sonnet 5.5) ─► validate ─► RESOLVE (engine, seed C01-E001-1) ─► SCRIPT (Sonnet 5.5 / Opus 5.5)
   ─► CONTINUITY (mechanical + Haiku 4.5) ─► ASSEMBLE timeline ─► RENDER ─► WIKI FACTS (Haiku) ─► PACKAGING (Haiku)
   ─► archive episodes/<id>/ ─► commit state/ ─► rebuild wiki/docs ─► GitHub Pages
```

1. **Plan** — the planner sees the bible (with its `SECRET` blocks), the dossiers, the campaign beat, the compact state and what viewers already know (the wiki canon). It declares *intents only*: scenes with cast and marks, checks with DCs and reasons, the encounter with positions, state proposals (optionally conditional on a roll: `"if": "e1.won"`). `validate_plan` rejects anything the engine or the stage can't honour (unknown skills or monsters, squares inside props, enemies adjacent at the start, missing party members...) and the planner gets the list back.
2. **Resolve** — the engine rolls every check and runs the fight with one seeded `Dice`. After a won fight nobody is left dying (`triage`, bible 10 §5). Valid proposals are applied; the writer receives only results and a numbered action log.
3. **Script** — the writer turns results into scenes: dialogue in each character's voice, `{op: "check", id: "c1"}` where a roll is shown, `{op: "encounter", id: "e1"}` where the fight plays, and Storyteller lines placed "after action N" of the fight.
4. **Continuity** — a free mechanical pass (every roll placed exactly once, speakers on stage, ≤ 140 characters per box, banned phrases and slang, no numbers in narration after a roll, spoiler phrases from `bible/spoilers.json`, the episode ends on a party member) and then a Haiku review for meaning (contradicting a roll, breaking a voice, leaking a secret). Blockers send the script back with the list.
5. **Assemble** — adds the title, the Storyteller's intro, scene cuts and location cards, walking paths around props, camera framing for whoever speaks, the dice tray for every check (the logged roll), the whole fight from the director, chapter markers and "Next time".
6. **Wiki and packaging** — these steps only ever see a *public* context (no bible secrets, no dossier secrets), extract what viewers now know, and every generated page is checked against the spoiler list before it is written. Packaging writes the YouTube title, hook and tags; chapters, the seed line and credits are appended mechanically; the thumbnail is a clean frame of the chosen moment.

Offline, `ReplayClient` serves `fixtures/<id>/<step>.json` and estimates token usage from the real prompt sizes, so the whole pipeline (and its cost ledger) runs in CI without a key. `--record` runs live and saves new fixtures.

### Episode 1: "Lantern Thirty-Seven"

Produced end to end from the fixtures: 5 scenes, 4 checks (Tamsin's Sleight of Hand ✔, Ilsevel's Investigation ✔, Brannoc's Perception ✘, Oriel's Medicine ✘), a 3-round fight with 46 logged rolls in which Ilsevel goes down and is brought back by Oriel's Healing Word, ~9.3 minutes. See `episodes/C01-E001/`.

### Overnight production (agent mode)

Without an API key, a scheduled Claude session can play every Claude step itself: `run_episode.py N --agent` writes the exact prompt the API would receive to `episodes/<id>/pending/<step>.md` and stops (exit code 3); the session writes `fixtures/<id>/<step>.json` and runs again. Rejected outputs (invalid plan, continuity blockers, spoilers) are moved aside and the next prompt carries the reasons. `production/queue.json` lists the work for Episodes 2-10 (maps, props and sprites, then each episode in order), `scripts/production.py` hands out the next ready task and holds a lock so overlapping hourly runs don't collide, and `production/RUNBOOK.md` is the procedure each run follows. Every finished episode advances `state/`, rebuilds `wiki/docs/` (redeployed to GitHub Pages on push) and its video is rendered on GitHub Actions and attached to a release tagged with the episode id (`.github/workflows/release.yml`; `scripts/publish_video.py` does the same by hand where a token allows it).

Scheduled sessions can read this repository but not push to it, so their work travels through Google Drive: `scripts/relay.py pack` turns what a shift changed into a plain-text bundle (every file hash-checked), the shift uploads it to the production Drive folder (`production/relay.json`), and `.github/workflows/relay.yml` applies new bundles every 10 minutes, regenerates everything derived (maps from their generators, committed episodes from their fixtures), runs the tests, commits, and starts the wiki and release workflows. `production/applied.json` lists every bundle applied or rejected. The workflow needs the Drive folder shared as "Anyone with the link" and a `DRIVE_API_KEY` repository secret (a Google API key with the Drive API enabled).

`state/genesis/` keeps the series-start state: tests, demos and the Episode 1 replay use it, while `state/` moves forward with each committed episode. An archived episode replays from its own `episodes/<id>/state_before/`.

Map tools: `scripts/maps/<id>.py` generate the map JSON, `scripts/map_preview.py <id> out.png --points --blocked` renders a whole map for review, `scripts/tileset_atlas.py` draws a labelled grid over any pack tileset to pick tiles.

### Costs

`scripts/cost_report.py C01-E001` re-prices the measured ledger: about **$0.10** for an ordinary episode (Sonnet writes, Batch API, shared cache), **$0.18** for a premiere/finale (Opus writes), **≈ $2.50 a month** and **≈ $73 for the whole 474-episode series** including the Fable 5.1 campaign plans. Without batching and caching an ordinary episode is about $0.24. Offline numbers are estimates (3.2 characters per token); live runs record the API's own usage.

## Before broadcast: verification checklist

The numbers in `data/*.json` were entered from the 2024 rules as known and are flagged `"verified": false`. Before an episode that uses a monster, spell or table is published:

1. Check the entry against the SRD 5.2 text.
2. Fix any difference and set `"verified": true`.
3. Re-run the tests.

Also confirm every spell in the dossiers' level plans exists in SRD 5.2.

## Licence and attribution

Art, music and SFX: *Ninja Adventure Asset Pack* by Pixel-boy & AAA (CC0). Fonts: Pixelify Sans and Tiny5 (OFL 1.1). Details in `assets/CREDITS.md`.

This work includes material from the System Reference Document 5.2 ("SRD 5.2") by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2 is licensed under the Creative Commons Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode. (Confirm this wording against the official SRD 5.2 page before launch.)

The world, characters, story and code are original. The project is compatible with fifth edition and is not affiliated with or endorsed by Wizards of the Coast.
