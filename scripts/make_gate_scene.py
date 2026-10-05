#!/usr/bin/env python3
"""Phase 2 gate: a ~60-second test scene rendered to 1080p from a timeline file.

1. Runs a real fight in the rules engine (seeded, every roll logged).
2. The director turns its events into battle cues.
3. A hand-written opening and closing (the C1E1 cold open) wrap the fight.
4. The timeline is saved to assets/timelines/gate_test_scene.json and rendered.

    python scripts/make_gate_scene.py                 # full 1080p render
    python scripts/make_gate_scene.py --scale 2       # quicker 960x540 preview
    python scripts/make_gate_scene.py --timeline-only # just write the JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc.ai import simple_policy  # noqa: E402
from pqc.combat import Encounter  # noqa: E402
from pqc.dice import Dice  # noqa: E402
from pqc.render.director import battle_cues  # noqa: E402
from pqc.state import GENESIS_PARTY_DIR, load_party, monster_from_data  # noqa: E402

SEED = "C01-E001-GATE-135"
NAMES = {"brannoc": "Brannoc", "ilsevel": "Ilsevel", "tamsin": "Tamsin", "oriel": "Oriel",
         "goblin-1": "Goblin", "goblin-2": "Goblin", "goblin-3": "Goblin Runt"}
KINDS = {"goblin-1": "goblin_warrior", "goblin-2": "goblin_warrior", "goblin-3": "goblin_minion"}


# Engine squares are the map's tiles: the fight happens where the intro leaves everyone.
START = {"oriel": (21, 10), "tamsin": (17, 12), "ilsevel": (19, 15), "brannoc": (22, 12)}
GOBLINS = {"goblin-1": ("goblin_warrior", (19, 19)), "goblin-2": ("goblin_warrior", (20, 20)),
           "goblin-3": ("goblin_minion", (22, 20))}


def fight(seed: str = SEED) -> tuple[dict, dict]:
    from pqc.render.assets import Assets
    from pqc.render.tilemap import TileMap
    assets = Assets()
    blocked = TileMap.load("brindle_cross", assets).blocked(assets)
    p = load_party(GENESIS_PARTY_DIR)
    for k, v in START.items():
        p[k].pos = v
    goblins = [monster_from_data(kind, gid, pos=pos) for gid, (kind, pos) in GOBLINS.items()]
    enc = Encounter(list(p.values()) + goblins, Dice(seed), name="Goblins on the Lantern Road", occupied_extra=blocked)
    result = enc.run(simple_policy)
    types = {(c.id, a.id): a.type for c in enc.creatures.values() for a in c.attacks}
    return result, types


def timeline(seed: str = SEED) -> dict:
    result, types = fight(seed)
    battle = battle_cues(result, kinds=KINDS, names=NAMES, attack_types=types, music="battle", origin=(0, 0))
    intro = [
        {"op": "title", "lines": ["NAT 20 PIXELS", "Episode 1 - Lantern Thirty-Seven"], "duration": 2.6},
        {"op": "scene", "map": "brindle_cross", "time_of_day": "dusk", "camera": [19, 11]},
        {"op": "fade", "from": "black", "to": "clear", "duration": 1.0, "wait": False},
        {"op": "dm_intro", "title": "Lantern Thirty-Seven",
         "subtitle": "Campaign 1: The Lantern Road  -  Level 1  -  3 Emberfall 1047 AK",
         "text": "Brindle Cross is a crossroads village on the southern edge of the Lanternmarch, where the oldest "
                 "lantern road in the Vael begins. Tonight four strangers share its market square at dusk: a soldier "
                 "carrying dispatches, a Lamplighter archivist, a card player with a borrowed name, and the shrine's "
                 "young acolyte. None of them knows the others yet. That is about to change."},
        {"op": "spawn", "actor": "oriel", "at": [21, 10], "facing": "up", "name": "Oriel"},
        {"op": "spawn", "actor": "tamsin", "at": [17, 12], "facing": "right", "name": "Tamsin"},
        {"op": "spawn", "actor": "ilsevel", "at": [19, 15], "facing": "down", "name": "Ilsevel"},
        {"op": "spawn", "actor": "brannoc", "at": [27, 11], "facing": "left", "name": "Brannoc"},
        {"op": "music", "track": "calm_village", "fade_in": 1.0, "volume": 0.5},
        {"op": "location_card", "text": "Brindle Cross  -  The Market Square  -  Dusk", "duration": 3.0},
        {"op": "wait", "seconds": 0.6},
        {"op": "say", "speaker": "oriel", "text": "Hold the light. Hold the road. Hold on to each other."},
        {"op": "say", "speaker": "tamsin", "text": "Lovely prayer, Sunshine. Does it work on card games?", "emote": "smile"},
        {"op": "move", "actor": "brannoc", "path": [[23, 11], [22, 12]], "face": "left", "wait": False},
        {"op": "say", "speaker": "brannoc", "text": "Dispatches for Fort Harrow. Is that lantern meant to do that?"},
        {"op": "face", "actor": "oriel", "facing": "down"},
        {"op": "face", "actor": "tamsin", "facing": "down"},
        {"op": "camera", "to": [20, 19], "duration": 1.4},
        {"op": "lantern", "id": "lantern_road.037", "state": "dead", "flicker": 1.8,
         "unlight": {"radius": 70, "grow": 3.0, "strength": 0.6}},
        {"op": "time_of_day", "preset": "evening", "duration": 2.5, "wait": False},
        {"op": "music_stop", "fade_out": 1.5},
        {"op": "narrate", "text": "The lantern gutters once. Then the road is dark."},
        {"op": "emote", "actor": "ilsevel", "emote": "exclaim", "duration": 1.2, "sfx": "alert"},
        {"op": "say", "speaker": "ilsevel",
         "text": "Technically, a lantern cannot simply go out. Someone has taken its core."},
        {"op": "spawn", "actor": "goblin-1", "sprite": "goblin_warrior", "at": [19, 25], "facing": "up"},
        {"op": "spawn", "actor": "goblin-2", "sprite": "goblin_warrior", "at": [20, 25], "facing": "up"},
        {"op": "spawn", "actor": "goblin-3", "sprite": "goblin_minion", "at": [21, 26], "facing": "up"},
        {"op": "music", "track": "tension", "fade_in": 0.3, "volume": 0.5},
        {"op": "move", "actor": "goblin-1", "path": [[19, 19]], "speed": 5, "wait": False},
        {"op": "move", "actor": "goblin-2", "path": [[20, 20]], "speed": 5, "wait": False},
        {"op": "move", "actor": "goblin-3", "path": [[22, 20]], "speed": 5},
        {"op": "emote", "actor": "tamsin", "emote": "alert", "duration": 1.0},
        {"op": "say", "speaker": "tamsin", "text": "Company. Ugly company."},
        {"op": "say", "speaker": "brannoc", "text": "Get behind the shield.", "emote": "angry"},
    ]
    outro = [
        {"op": "camera", "to": [20, 13], "duration": 0.8},
        {"op": "music", "track": "calm_village", "fade_in": 1.0, "volume": 0.4},
        {"op": "say", "speaker": "brannoc", "text": "Report. Short version."},
        {"op": "say", "speaker": "tamsin", "text": "We won. Short enough?", "emote": "happy"},
        {"op": "narrate", "text": "Next time: the road beyond Lantern Thirty-Seven."},
        {"op": "music_stop", "fade_out": 1.2},
        {"op": "fade", "to": "black", "duration": 1.2},
    ]
    return {"schema": "pqc/timeline@1", "id": "gate_test_scene", "title": "Phase 2 gate - C1E1 test scene",
            "fps": 30, "seed": seed, "tail": 0.3, "cues": intro + battle + outro}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--timeline-only", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "render_out" / "gate_test_scene.mp4"))
    args = ap.parse_args()
    tl = timeline()
    path = ROOT / "assets" / "timelines" / "gate_test_scene.json"
    path.write_text(json.dumps(tl, indent=1, ensure_ascii=False))
    print(f"timeline: {path.relative_to(ROOT)} ({len(tl['cues'])} cues)")
    if args.timeline_only:
        return 0
    from pqc.render.video import render
    stills = [6, 20, 30, 45, 60, 70, 80, 90, 100, 110]
    render(tl, args.out, scale=args.scale, stills=stills, stills_dir=ROOT / "render_out" / "stills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
