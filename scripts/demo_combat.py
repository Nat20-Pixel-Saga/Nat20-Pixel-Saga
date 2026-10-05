#!/usr/bin/env python3
"""Phase 1 gate: resolve a full SRD combat from JSON with every roll logged.

Runs C1E1's tutorial fight — goblins raid the Crooked Kettle — with the real
party sheets, the deterministic policy, and a fixed seed. Writes the episode
record to ``out/C01-E001.json`` and prints a readable log with dice overlays.

    python scripts/demo_combat.py [--seed C01-E001-1] [--quiet]
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
from pqc.schema import validate_named  # noqa: E402
from pqc.state import GENESIS_PARTY_DIR, load_party, monster_from_data  # noqa: E402


def build(seed: str) -> Encounter:
    party = load_party(GENESIS_PARTY_DIR)
    # The common room of the Crooked Kettle: party near the hearth, goblins at the doors.
    positions = {"brannoc": (5, 4), "oriel": (4, 5), "ilsevel": (2, 4), "tamsin": (3, 3)}
    for cid, pos in positions.items():
        party[cid].pos = pos
    goblins = [
        monster_from_data("goblin_warrior", "goblin-1", pos=(9, 4), name="Goblin Warrior"),
        monster_from_data("goblin_warrior", "goblin-2", pos=(9, 6), name="Goblin Warrior"),
        monster_from_data("goblin_minion", "goblin-3", pos=(10, 2), name="Goblin Minion"),
        monster_from_data("goblin_minion", "goblin-4", pos=(8, 8), name="Goblin Minion"),
    ]
    return Encounter(list(party.values()) + goblins, Dice(seed), name="Raid on the Crooked Kettle")


def describe(ev: dict, rolls: dict) -> str | None:
    t = ev["t"]
    if t == "initiative":
        return f"  initiative {ev['actor']}: {ev['total']}"
    if t == "turn_start":
        return f"\n— {ev['actor']}'s turn (round {ev['round']}, HP {ev['hp']})"
    if t == "move":
        return f"  moves {ev['frm']} → {ev['to']}"
    if t == "attack":
        if ev.get("blocked"):
            return f"  {ev['actor']} attacks {ev['target']} — blocked by {ev['blocked']}"
        line = f"  {ev['actor']} {ev['attack']} → {ev['target']}: {ev['overlay']}"
        if ev["hit"]:
            line += f"  dmg {ev['damage']['total']} (HP→{ev['damage']['hp_after']})"
            if ev.get("sneak_attack"):
                line += " +Sneak Attack"
        if ev.get("graze"):
            line += f"  graze {ev['graze']['total']}"
        return line
    if t == "cast":
        parts = []
        for r in ev["results"]:
            bit = r.get("overlay") or ""
            if "damage" in r:
                bit += f" dmg {r['damage']['total']}"
            if "amount" in r:
                bit += f" healed {r['amount']}"
            if r.get("effect"):
                bit += f" [{r['effect']}]"
            parts.append(f"{r['target']}: {bit.strip()}")
        return f"  {ev['actor']} casts {ev['spell']} (L{ev['level']}) — " + "; ".join(parts)
    if t in ("down", "death"):
        return f"  ** {ev['actor']} {'falls' if t == 'down' else 'dies'} **"
    if t == "death_save":
        return f"  death save {ev['actor']}: d20 {ev['natural']} → {ev['result']} {ev['death_saves']}"
    if t in ("reaction", "second_wind", "use_item", "stabilize", "hide", "dodge", "disengage", "dash",
             "concentration_check", "concentration_end", "illegal_intent", "trait"):
        return "  " + json.dumps({k: v for k, v in ev.items() if k not in ("seq", "round")}, ensure_ascii=False)
    if t == "encounter_end":
        return f"\n=== {ev['winner']} win after {ev['rounds']} rounds · {ev['xp']} XP ==="
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="C01-E001-1")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    enc = build(args.seed)
    result = enc.run(simple_policy)
    rolls = {r["id"]: r for r in result["rolls"]}
    if not args.quiet:
        for ev in result["events"]:
            line = describe(ev, rolls)
            if line:
                print(line)

    ok = Dice.verify_log(args.seed, result["rolls"])
    episode = {
        "schema": "pqc/episode@1", "id": "C01-E001", "campaign": 1, "episode": 1, "title": "Lantern Thirty-Seven",
        "seed": args.seed, "attempt": int(args.seed.rsplit("-", 1)[1]), "status": "resolved",
        "checks": [], "encounters": [{"name": result["name"], "winner": result["winner"], "rounds": result["rounds"],
                                      "xp": result["xp"], "events": result["events"], "combatants": result["combatants"]}],
        "rolls": result["rolls"], "state_changes": [], "xp_awarded": result["xp"],
    }
    errors = validate_named(episode, "episode")
    out = ROOT / "out" / "C01-E001.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(episode, indent=2, ensure_ascii=False))
    print(f"\n{len(result['rolls'])} rolls logged · replay verified: {ok} · schema errors: {len(errors)} · wrote {out.relative_to(ROOT)}")
    return 0 if ok and not errors and result["finished"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
