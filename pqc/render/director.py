"""Director: rules-engine events -> renderer cues.

Takes the result of ``Encounter.run()`` (events + roll log) and produces the
battle part of a timeline. Every cue carries the *logged* roll, so the dice on
screen are exactly the dice the engine rolled. Narration is left to the writer
(Phase 3); the director only marks where it would help with ``narrate_hint``.
"""
from __future__ import annotations

import re

from .. import data

MONSTER_FX = {"bite": "claw", "claw": "claw", "slam": "slash"}


def default_sprite(creature_summary: dict, kinds: dict[str, str]) -> str:
    cid = creature_summary["id"]
    if cid in kinds:
        return kinds[cid]
    if creature_summary.get("team") == "party":
        return cid
    return re.sub(r"[^a-z0-9]+", "_", creature_summary["name"].lower()).strip("_")


def _line(roll: dict, verb_ok="HIT", verb_fail="MISS", target_word="AC") -> str:
    mod = roll["modifier"]
    faces = roll["rolls"][:2]
    adv = ""
    if roll.get("advantage") == "advantage":
        adv = "ADV "
    elif roll.get("advantage") == "disadvantage":
        adv = "DIS "
    nat = roll["natural"] if roll["kind"] == "d20" else roll["total"]
    sign = "+" if mod >= 0 else "-"
    s = f"{adv}{nat} {sign} {abs(mod)} = {roll['total']}"
    if roll.get("dc") is not None:
        s += f" vs {target_word} {roll['dc']}"
    if roll.get("critical"):
        return s + " CRIT!"
    if roll.get("success") is True:
        return s + f" {verb_ok}"
    if roll.get("success") is False:
        return s + f" {verb_fail}"
    return s


def _shift(p, origin):
    return [p[0] + origin[0], p[1] + origin[1]]


def battle_cues(result: dict, kinds: dict[str, str] | None = None, names: dict[str, str] | None = None,
                attack_types: dict[tuple[str, str], str] | None = None, max_actions: int | None = None,
                music: str = "battle", origin: tuple[int, int] | None = (0, 0), turn_markers: bool = True) -> list[dict]:
    """Convert an encounter result into battle cues.

    ``attack_types`` maps (creature id, attack id) -> "melee" | "ranged" (from
    the live encounter); missing entries are inferred from the attack id.
    """
    kinds = kinds or {}
    names = names or {}
    attack_types = attack_types or {}
    rolls = {r["id"]: r for r in result["rolls"]}
    events = result["events"]
    start = next(e for e in events if e["t"] == "encounter_start")
    party, enemies = [], []
    for c in start["combatants"]:
        entry = {"id": c["id"], "sprite": default_sprite(c, kinds), "hp": c["hp"], "max_hp": c["max_hp"],
                 "name": names.get(c["id"], c["id"].split("-")[0].capitalize())}
        if origin is not None:
            entry["at"] = _shift(c["pos"], origin)
        (party if c["team"] == "party" else enemies).append(entry)
    team = {c["id"]: c["team"] for c in start["combatants"]}
    pos = {c["id"]: tuple(c["pos"]) for c in start["combatants"]}
    cues: list[dict] = [{"op": "battle_start", "party": party, "enemies": enemies, "music": music}]
    if origin is None:
        cues[0]["arena"] = True
    ini = {e["actor"]: e["total"] for e in events if e["t"] == "initiative"}
    order = next((e["order"] for e in events if e["t"] == "initiative_order"), [])
    if ini and order:
        cues.append({"op": "initiative", "order": [
            {"id": cid, "name": names.get(cid, cid.replace("-", " ").title()), "total": ini.get(cid, 0),
             "team": team.get(cid)} for cid in order]})
    n_actions = 0
    o = origin or (0, 0)
    # Opportunity attacks that interrupt a move: index of the attack event by seq.
    seq_index = {e["seq"]: i for i, e in enumerate(events)}

    def title(cid):
        return names.get(cid, cid.replace("-", " ").title())

    pending_shield: list[dict] = []
    deferred: dict[int, list[dict]] = {}  # move remainder to emit after an opportunity attack
    for ev in events:
        t = ev["t"]
        if t == "turn_start" and turn_markers and origin is not None:
            if ev["actor"] in team and (max_actions is None or n_actions < max_actions):
                cues.append({"op": "battle_turn", "actor": ev["actor"], "round": ev["round"]})
            continue
        if t == "move" and origin is not None:
            path = [tuple(p) for p in ev["path"]]
            # Split the walk where an opportunity attack against the mover happens.
            split = None
            for nxt in events[seq_index[ev["seq"]] + 1:]:
                if nxt["t"] in ("move", "turn_end", "cast"):
                    break
                if nxt["t"] == "attack" and nxt.get("opportunity") and nxt["target"] == ev["actor"]:
                    apos = pos.get(nxt["actor"])
                    for i in range(len(path) - 1):
                        if apos and max(abs(path[i][0] - apos[0]), abs(path[i][1] - apos[1])) <= 1 < \
                                max(abs(path[i + 1][0] - apos[0]), abs(path[i + 1][1] - apos[1])):
                            split = (i, nxt["seq"])
                            break
                    break
            if split:
                i, aseq = split
                cues.append({"op": "battle_move", "actor": ev["actor"], "path": [_shift(p, o) for p in path[:i + 1]]})
                deferred[aseq] = [{"op": "battle_move", "actor": ev["actor"],
                                   "path": [_shift(p, o) for p in path[i:]]}]
            elif len(path) > 1:
                cues.append({"op": "battle_move", "actor": ev["actor"], "path": [_shift(p, o) for p in path]})
            pos[ev["actor"]] = path[-1]
            continue
        if t in ("dash", "disengage", "dodge", "stand_up") or (t == "hide" and ev.get("success")):
            cues.append({"op": "battle_note", "actor": ev["actor"],
                         "text": {"dash": "Dash", "disengage": "Disengage", "dodge": "Dodge", "hide": "Hidden",
                                  "stand_up": "Stands up"}[t]})
            if t == "stand_up":
                cues.append({"op": "battle_revive", "actor": ev["actor"]})
            continue
        if t == "hide":
            cues.append({"op": "roll", "roll": rolls[ev["roll"]], "label": f"{title(ev['actor'])} - Hide (Stealth)",
                         "line": _line(rolls[ev["roll"]], "HIDDEN", "SEEN", "DC")})
            continue
        if max_actions is not None and n_actions >= max_actions and t not in ("encounter_end",):
            continue
        if t == "reaction" and ev.get("reaction") == "shield":
            pending_shield.append({"op": "battle_cast", "actor": ev["actor"], "spell": "shield",
                                   "results": [{"target": ev["actor"], "effect": "shield"}],
                                   "label": f"{title(ev['actor'])} - Shield (reaction)",
                                   "line": f"AC rises to {ev['ac']}"})
        elif t == "attack" and not ev.get("blocked"):
            roll = rolls[ev["roll"]]
            atk_id = ev["attack"]
            kind = attack_types.get((ev["actor"], atk_id)) or ("ranged" if (":thrown" in atk_id or "bow" in atk_id
                                                                            or "crossbow" in atk_id) else "melee")
            cue = {"op": "battle_attack", "actor": ev["actor"], "target": ev["target"], "roll": roll,
                   "hit": ev["hit"], "critical": ev["critical"], "ranged": kind == "ranged",
                   "label": ("Opportunity attack: " if ev.get("opportunity") else "") +
                            f"{title(ev['actor'])} - {atk_id.split(':')[0].replace('_', ' ').title()}",
                   "line": _line(roll)}
            if ev["hit"]:
                cue["damage"] = ev["damage"]["total"]
                cue["hp_after"] = ev["damage"]["hp_after"]
                cue["sneak_attack"] = bool(ev.get("sneak_attack"))
                base = atk_id.split(":")[0]
                if base in MONSTER_FX:
                    cue["fx"] = MONSTER_FX[base]
            elif ev.get("graze"):
                cue["hit"] = True
                cue["damage"] = ev["graze"]["total"]
                cue["hp_after"] = ev["graze"]["hp_after"]
                cue["line"] += " (graze)"
            cues += pending_shield
            pending_shield = []
            cues.append(cue)
            cues += deferred.pop(ev["seq"], [])
            n_actions += 1
        elif t == "cast":
            cues += pending_shield
            pending_shield = []
            sp = data.spell(ev["spell"])
            per_target: dict[str, dict] = {}
            first_roll = None
            darts = 0
            for r in ev["results"]:
                tid = r["target"]
                agg = per_target.setdefault(tid, {"target": tid})
                if "roll" in r and r["roll"] in rolls and sp["kind"] in ("attack", "save") and first_roll is None:
                    first_roll = rolls[r["roll"]]
                if "dart" in r:
                    darts += 1
                if "damage" in r:
                    agg["damage"] = agg.get("damage", 0) + r["damage"]["total"]
                    agg["hp_after"] = r["damage"]["hp_after"]
                if sp["kind"] == "attack":
                    agg["hit"] = r.get("hit")
                if sp["kind"] == "save":
                    agg["saved"] = r.get("saved")
                if sp["kind"] == "heal":
                    agg["heal"] = r.get("amount", 0)
                    agg["hp_after"] = r.get("hp_after")
                    agg["revived"] = r.get("revived", False)
                if sp["kind"] == "buff":
                    agg["effect"] = r.get("effect")
            cue = {"op": "battle_cast", "actor": ev["actor"], "spell": ev["spell"],
                   "results": list(per_target.values()),
                   "label": f"{title(ev['actor'])} - {sp['name']}" + (f" (level {ev['level']})" if ev["level"] else "")}
            if darts:
                cue["count"] = max(1, darts // max(1, len(per_target)))
            if ev.get("area") and origin is not None:
                cue["area"] = [_shift(q, o) for q in ev["area"]]
                cue["toward"] = _shift(ev["toward"], o)
            if first_roll:
                cue["roll"] = first_roll
                if sp["kind"] == "attack":
                    cue["line"] = _line(first_roll)
                else:
                    cue["line"] = f"{title(first_roll['actor'])}: " + _line(first_roll, "SAVED", "FAILS", "DC")
            elif sp["kind"] == "heal":
                total = sum(v.get("heal", 0) for v in per_target.values())
                cue["line"] = f"Restores {total} HP"
            elif sp["kind"] == "auto":
                total = sum(v.get("damage", 0) for v in per_target.values())
                cue["line"] = f"{darts} darts, {total} force damage"
            elif sp["kind"] == "buff":
                cue["line"] = ", ".join(title(v["target"]) for v in per_target.values())
            cues.append(cue)
            cues += [{"op": "battle_revive", "actor": v["target"]} for v in per_target.values() if v.get("revived")]
            n_actions += 1
        elif t in ("second_wind", "use_item"):
            target = ev.get("target", ev["actor"])
            spell = "second_wind" if t == "second_wind" else ev.get("item", "potion_of_healing")
            cues.append({"op": "battle_cast", "actor": ev["actor"], "spell": spell,
                         "results": [{"target": target, "heal": ev["amount"], "hp_after": ev["hp_after"]}],
                         "label": f"{title(ev['actor'])} - " + ("Second Wind" if t == "second_wind" else "Potion of Healing"),
                         "line": f"Restores {ev['amount']} HP", "roll": dict(rolls[ev["roll"]], kind="dice")})
            if ev.get("revived"):
                cues.append({"op": "battle_revive", "actor": target})
            n_actions += 1
        elif t in ("down", "death"):
            if team.get(ev["actor"]) == "party":
                if t == "down":
                    cues.append({"op": "battle_faint", "actor": ev["actor"], "pc": True, "narrate_hint": "pc_down"})
            elif not any(c.get("op") == "battle_faint" and c.get("actor") == ev["actor"] for c in cues):
                cues.append({"op": "battle_faint", "actor": ev["actor"]})
        elif t == "death_save":
            roll = rolls[ev["roll"]]
            cues.append({"op": "roll", "roll": roll, "label": f"{title(ev['actor'])} - Death save",
                         "line": f"{roll['natural']} : {ev['result'].replace('_', ' ')}"})
        elif t == "encounter_end":
            cues += pending_shield
            cues.append({"op": "battle_end", "result": "victory" if ev["winner"] == "party" else "defeat",
                         "xp": ev["xp"]})
    return cues
