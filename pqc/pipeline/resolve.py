"""Resolve a plan with the rules engine.

The planner declared intents; here the engine rolls them, in scene order, from
one seeded ``Dice`` (``<episode>-<attempt>``). Output:

* the **episode record** (``pqc/episode@1``): every roll, check, fight and state change;
* the **outcomes** handed to the writer: results only, plus a numbered action log per fight;
* the battle cues for the assembler (the director's translation of the fight log);
* the party sheets and world state after the episode.

State proposals from the plan are applied here, deterministically and only
when valid; anything conditional on a roll is applied only if that roll went
that way.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field

from .. import data, features, progression
from ..ai import simple_policy
from ..checks import ability_check, contest, group_check, saving_throw
from ..combat import Encounter
from ..dice import Dice
from ..render.director import _line, battle_cues
from ..rules import ABILITIES, FLANKING_FROM_LEVEL, SKILLS
from ..schema import validate_named
from ..state import ROOT, character_from_sheet, load_json, monster_from_data, sheet_from_character

MANIFEST = ROOT / "assets" / "manifest.json"
MAPS = ROOT / "assets" / "maps"
PARTY = ("brannoc", "ilsevel", "tamsin", "oriel")


# ------------------------------------------------------------------ maps
def load_map(map_id: str) -> dict:
    return load_json(MAPS / f"{map_id}.json")


def blocked_squares(map_id: str) -> set[tuple[int, int]]:
    """Squares props make impassable (same rule as ``TileMap.blocked``, no images needed)."""
    m = load_map(map_id)
    props = load_json(MANIFEST)["props"]
    out = set()
    for p in m.get("props", []):
        spec = props[p["prop"]]
        mode = spec.get("solid", "none")
        _, _, w, h = spec["rect"]
        x, y = p["at"]
        if mode == "all":
            out |= {(x + dx, y + dy) for dx in range(w) for dy in range(h)}
        elif mode == "base":
            out |= {(x + dx, y + h - 1) for dx in range(w)}
    return out


def free_square(map_id: str, xy, taken=()) -> str | None:
    """Why ``xy`` can't hold a creature, or None if it can."""
    m = load_map(map_id)
    w, h = m["size"]
    x, y = xy[0], xy[1]
    if not (0 <= x < w and 0 <= y < h):
        return f"{list(xy)} is outside the {w}x{h} map"
    if (x, y) in blocked_squares(map_id):
        return f"{list(xy)} is inside a prop"
    if (x, y) in taken:
        return f"{list(xy)} is already occupied"
    return None


# ------------------------------------------------------------- validation
def validate_plan(plan: dict, sheets: dict, world: dict) -> list[str]:
    """Schema plus everything the engine and the stage need to be true."""
    errors = validate_named(plan, "plan")
    if errors:
        return errors
    sprites = set(load_json(MANIFEST)["actors"])
    monsters = data.monsters()
    seen_ids = set()
    for sc in plan["scenes"]:
        if not (MAPS / f"{sc['map']}.json").exists():
            errors.append(f"{sc['id']}: map {sc['map']!r} does not exist yet")
            continue
        taken = set()
        for c in sc["cast"]:
            sprite = c.get("sprite", c["id"])
            if sprite not in sprites:
                errors.append(f"{sc['id']}: cast {c['id']!r} has no sprite {sprite!r}")
            why = free_square(sc["map"], c["at"], taken)
            if why:
                errors.append(f"{sc['id']}: cast {c['id']} at {why}")
            taken.add(tuple(c["at"][:2]))
        for ch in sc.get("checks", []):
            if ch["id"] in seen_ids:
                errors.append(f"{ch['id']}: duplicate id")
            seen_ids.add(ch["id"])
            actors = ch.get("group") or [ch["actor"]]
            for a in actors:
                if a not in sheets:
                    errors.append(f"{ch['id']}: actor {a!r} is not a party member")
                elif sheets[a]["hp"]["current"] <= 0 and not ch.get("offscreen"):
                    errors.append(f"{ch['id']}: {a} is unconscious")
            if ch.get("skill") and ch["skill"] not in SKILLS:
                errors.append(f"{ch['id']}: unknown skill {ch['skill']!r}")
            if ch.get("ability") and ch["ability"] not in ABILITIES:
                errors.append(f"{ch['id']}: unknown ability {ch['ability']!r}")
            if not ch.get("skill") and not ch.get("ability"):
                errors.append(f"{ch['id']}: needs a skill or an ability")
            if ch.get("save") and not ch.get("ability"):
                errors.append(f"{ch['id']}: a saving throw needs an ability")
            con = ch.get("contest")
            if ch.get("dc") is None and not con:
                errors.append(f"{ch['id']}: needs a dc or a contest")
            if ch.get("dc") is not None and ch["dc"] >= 20 and len(ch["reason"]) < 25:
                errors.append(f"{ch['id']}: DC {ch['dc']} needs a justification in 'reason'")
            if con:
                if con.get("monster") and con["monster"] not in monsters:
                    errors.append(f"{ch['id']}: unknown monster {con['monster']!r}")
                if con.get("actor") and con["actor"] not in sheets:
                    errors.append(f"{ch['id']}: contest actor {con['actor']!r} unknown")
                if not con.get("monster") and not con.get("actor"):
                    errors.append(f"{ch['id']}: contest needs an actor or a monster")
        enc = sc.get("encounter")
        if enc:
            if enc["id"] in seen_ids:
                errors.append(f"{enc['id']}: duplicate id")
            seen_ids.add(enc["id"])
            taken = set()
            for e in enc["enemies"]:
                if e["kind"] not in monsters:
                    errors.append(f"{enc['id']}: unknown monster {e['kind']!r}")
                if e.get("sprite", e["kind"]) not in sprites:
                    errors.append(f"{enc['id']}: no sprite {e.get('sprite', e['kind'])!r}")
                why = free_square(sc["map"], e["at"], taken)
                if why:
                    errors.append(f"{enc['id']}: enemy {e['id']} at {why}")
                taken.add(tuple(e["at"][:2]))
            ids = [e["id"] for e in enc["enemies"]]
            if len(ids) != len(set(ids)) or set(ids) & set(PARTY):
                errors.append(f"{enc['id']}: enemy ids must be unique and differ from the party's")
            for pid, s in sheets.items():
                if s["hp"]["current"] > 0 and pid not in enc["party_at"]:
                    errors.append(f"{enc['id']}: party_at is missing {pid}")
            for pid, xy in enc["party_at"].items():
                if pid not in sheets:
                    errors.append(f"{enc['id']}: party_at has unknown {pid!r}")
                why = free_square(sc["map"], xy, taken)
                if why:
                    errors.append(f"{enc['id']}: {pid} at {why}")
                taken.add(tuple(xy[:2]))
            for side, cond in (enc.get("surprise") or {}).items():
                ref, _, want = str(cond).partition(".")
                if side not in ("party", "enemies") or ref not in seen_ids or want not in ("success", "failure"):
                    errors.append(f"{enc['id']}: surprise needs {{'party'|'enemies': '<earlier check id>.success|failure'}}, "
                                  f"got {side!r}: {cond!r}")
            gaps = [max(abs(a[0] - e["at"][0]), abs(a[1] - e["at"][1]))
                    for a in enc["party_at"].values() for e in enc["enemies"]]
            if gaps and min(gaps) <= 1:
                errors.append(f"{enc['id']}: the fight must not start with enemies adjacent to the party")
    for i, p in enumerate(plan.get("state_proposals", [])):
        cond = p.get("if")
        if cond:
            ref, _, want = cond.partition(".")
            if ref not in seen_ids or want not in ("success", "failure", "won", "lost"):
                errors.append(f"state_proposals[{i}]: bad condition {cond!r}")
        if p["type"] == "travel" and not (isinstance(p.get("days"), int) and 1 <= p["days"] <= 30):
            errors.append(f"state_proposals[{i}]: travel needs 'days' from 1 to 30")
        camp = p.get("camp") if p["type"] == "rest" else None
        if camp is not None:
            for w in camp.get("watches", []):
                for who in (w if isinstance(w, list) else [w]):
                    if who not in sheets:
                        errors.append(f"state_proposals[{i}]: watch keeper {who!r} is not a party member")
    return errors


# ---------------------------------------------------------------- results
@dataclass
class Resolution:
    episode: dict
    outcomes: dict
    battles: dict = field(default_factory=dict)       # encounter id -> {"cues", "actions", "result"}
    sheets_after: dict = field(default_factory=dict)
    world_after: dict = field(default_factory=dict)
    check_rolls: dict = field(default_factory=dict)   # check id -> [roll dicts shown on screen]

    def outcomes_text(self) -> str:
        return json.dumps(self.outcomes, ensure_ascii=False, indent=1)


def _name(sheets, cid):
    return sheets[cid]["name"].split()[0] if cid in sheets else cid.replace("-", " ").replace("_", " ").title()


def _check_label(sheets, ch) -> str:
    what = (ch.get("skill") or ch.get("ability") or "").replace("_", " ").title()
    if ch.get("save"):
        what = f"{ch['ability'].upper()} save"
    who = "Party" if ch.get("group") else _name(sheets, ch["actor"])
    return f"{who} - {what}"


def resolve(plan: dict, sheets: dict, world: dict, seed: str, attempt: int = 1) -> Resolution:
    dice = Dice(seed)
    party = {cid: character_from_sheet(s) for cid, s in sheets.items()}
    checks_out, encounters_out, outcome_checks, outcome_fights = [], [], [], []
    battles, check_rolls, results, aftermath = {}, {}, {}, []

    for sc in plan["scenes"]:
        for ch in sc.get("checks", []):
            rec, rolls, success, extra = _roll_check(ch, party, dice)
            results[ch["id"]] = "success" if success else "failure"
            check_rolls[ch["id"]] = [r.to_dict() for r in rolls]
            checks_out.append({"id": ch["id"], "actor": ch["actor"], "skill": ch.get("skill"),
                               "ability": ch.get("ability"), "dc": rec.dc, "roll": rec.id, "success": success,
                               "reason": ch["reason"], "offscreen": bool(ch.get("offscreen"))})
            margin = rec.total - rec.dc if rec.dc is not None else None
            outcome_checks.append({
                "id": ch["id"], "scene": sc["id"], "who": ch.get("group") or ch["actor"],
                "what": _check_label(sheets, ch), "dc": rec.dc, "result": "SUCCESS" if success else "FAILURE",
                "margin": margin, "natural": rec.natural,
                "note": ("natural 20" if rec.natural == 20 else "natural 1" if rec.natural == 1 else
                         ("barely" if margin is not None and abs(margin) <= 1 else
                          "by a lot" if margin is not None and abs(margin) >= 6 else "")),
                "means": ch.get("on_success") if success else ch.get("on_failure"), **extra})
        enc = sc.get("encounter")
        if enc:
            enc = encounter_options(enc, plan["episode_id"], sheets, results, party)
            b = _fight(enc, sc["map"], party, sheets, dice)
            battles[enc["id"]] = b
            r = b["result"]
            if features.enabled("xp_banner", plan["episode_id"]) and r["winner"] == "party":
                for cue in b["cues"]:          # what each character gets, in a font whose X doesn't read as H
                    if cue["op"] == "battle_end":
                        cue["banner"] = f"Victory!  +{r['xp'] // max(1, len(party))} XP each"
                        cue["banner_font"] = "text"
            results[enc["id"]] = "won" if r["winner"] == "party" else "lost"
            encounters_out.append({"name": enc["name"], "winner": r["winner"], "rounds": r["rounds"], "xp": r["xp"],
                                   "events": r["events"], "combatants": r["combatants"]})
            outcome_fights.append({"id": enc["id"], "scene": sc["id"], "winner": r["winner"], "rounds": r["rounds"],
                                   "xp": r["xp"], "actions": b["actions"], "end_state": b["end_state"]})
            if (enc.get("options") or {}).get("surprised"):
                outcome_fights[-1]["surprised"] = enc["options"]["surprised"]
            if r["winner"] == "party":
                for a in triage(party, dice, n0=len(aftermath)):
                    a["scene"] = next((s2["id"] for s2 in plan["scenes"][plan["scenes"].index(sc) + 1:]), sc["id"])
                    aftermath.append(a)
                    check_rolls[a["id"]] = [a.pop("_roll")]
                    results[a["id"]] = "success"

    sheets_after = {cid: sheet_from_character(c) for cid, c in party.items()}
    world_after = copy.deepcopy(world)
    night: list[dict] = []
    changes = apply_proposals(plan, results, sheets_after, world_after, dice=dice, night=night)
    xp_total = sum(e["xp"] for e in encounters_out if e["winner"] == "party")
    per = xp_total // max(1, len(sheets_after))
    for s in sheets_after.values():
        s["xp"] = s.get("xp", 0) + per
    if per:
        changes.append({"type": "xp", "amount_each": per, "source": "encounters", "applied": True})
    camp, ep = int(plan["episode_id"][1:3]), int(plan["episode_id"][-3:])
    level_ups, progress = [], None
    if features.enabled("level_ups", plan["episode_id"]):
        level_ups, progress = _level_ups(camp, ep, sheets, sheets_after, changes)
    _advance_series(plan, world_after)

    record = {
        "schema": "pqc/episode@1", "id": plan["episode_id"], "campaign": camp, "episode": ep,
        "title": plan["title"], "seed": seed, "attempt": attempt, "status": "resolved",
        "in_world_date": dict(world["clock"]),
        "checks": checks_out, "encounters": encounters_out, "rolls": dice.export_log(),
        "state_changes": changes, "xp_awarded": per, "loot": [], "level_ups": level_ups,
    }
    if progress is not None:
        record["progress"] = progress
    outcomes = {"episode_id": plan["episode_id"], "seed": seed, "checks": outcome_checks, "fights": outcome_fights,
                "aftermath": aftermath,
                "party_after": {cid: {"hp": f"{s['hp']['current']}/{s['hp']['max']}",
                                      "conditions": sorted(s.get("conditions", {}))} for cid, s in sheets_after.items()}}
    if night:
        outcomes["nights"] = night
    if progress is not None:
        for cid, pr in progress.items():
            outcomes["party_after"][cid].update(level=pr["level"], xp=pr["xp"], xp_to_next=pr["xp_to_next"])
        outcomes["level_ups"] = [{"who": r["id"], "level": r["to"], "new": r["new"], "hp_max": r["hp_max"],
                                  "still_to_choose": r["pending_choices"]} for r in level_ups]
    return Resolution(record, outcomes, battles, sheets_after, world_after, check_rolls)


def encounter_options(enc: dict, eid: str, sheets: dict, results: dict, party: dict) -> dict:
    """The rules a fight runs under, by episode (production/features.json): tactics 2, flanking once the
    whole party is above level 2 (bible 10 §4), and surprise from a watch check. The plan's own
    ``options`` win (e.g. ``"flanking": false`` for a fight that must not use it)."""
    opts = {}
    if features.enabled("tactics_v2", eid):
        opts["tactics"] = 2
    if features.enabled("flanking", eid) and sheets and min(s["level"] for s in sheets.values()) >= FLANKING_FROM_LEVEL:
        opts["flanking"] = True
    if enc.get("surprise") and features.enabled("camps", eid):
        opts["surprised"] = _surprised(enc, results, party)
    if not opts:
        return enc
    return {**enc, "options": {**opts, **(enc.get("options") or {})}}


def _surprised(enc: dict, results: dict, party: dict) -> list[str]:
    """``"surprise": {"party": "c3.failure", "enemies": "c3.success"}``: whoever the condition names is
    surprised (disadvantage on Initiative), e.g. when the watch did or didn't hear them coming."""
    out = []
    for side, cond in (enc.get("surprise") or {}).items():
        ref, _, want = cond.partition(".")
        if results.get(ref) == want:
            out += list(enc["party_at"]) if side == "party" else [e["id"] for e in enc["enemies"]]
    return out


def _level_ups(camp: int, ep: int, before: dict, sheets_after: dict, changes: list) -> tuple[list, dict]:
    """Level-ups at the end of the episode (bible 10 §7): by XP, with the campaign's milestone episodes
    topping XP up so their level always lands. Also the per-character progress for the end card."""
    from .context import campaign_entry
    try:
        milestone = campaign_entry(camp, ep)[1].get("milestone_level")
    except (FileNotFoundError, StopIteration):
        milestone = None
    reports = []
    for cid, s in sheets_after.items():
        reps, mxp = progression.advance(s, milestone)
        if mxp:
            changes.append({"type": "xp", "who": cid, "amount": mxp, "source": f"milestone (level {milestone})",
                            "applied": True})
        reports += reps
    progress = {cid: {"level_before": before[cid]["level"], "level": s["level"], "xp_before": before[cid].get("xp", 0),
                      "xp": s.get("xp", 0), "xp_to_next": progression.xp_to_next(s),
                      "next_at": progression.xp_for_level(s["level"] + 1) if s["level"] < 20 else None,
                      "level_start": progression.xp_for_level(s["level"])}
                for cid, s in sheets_after.items()}
    return reports, progress


def triage(party: dict, dice: Dice, n0: int = 0) -> list[dict]:
    """After a won fight, nobody is left dying (bible 10 §5 "After the fight"):
    each downed, living party member is brought back by the best means at hand,
    in this order - a healing spell from a conscious caster with a slot, the
    Spare the Dying cantrip, a DC 10 Wisdom (Medicine) check. Every roll is logged."""
    out = []
    for pid, c in party.items():
        if c.hp > 0 or c.dead:
            continue
        healers = [h for h in party.values() if h.hp > 0 and h.id != pid]
        best = None
        for h in healers:
            sc = h.spellcasting or {}
            known = set(sc.get("prepared", [])) | set(sc.get("known", [])) | set(sc.get("cantrips", []))
            slot = next((lvl for lvl in sorted(sc.get("slots", {})) if sc["slots"][lvl]["current"] > 0), None)
            for spell in ("healing_word", "cure_wounds"):
                if spell in known and slot:
                    best = best or ("spell", h, spell, slot)
            if "spare_the_dying" in known:
                best = best or ("cantrip", h, "spare_the_dying", None)
        n = n0 + len(out) + 1
        if best and best[0] == "spell":
            _, h, spell, slot = best
            sp = data.spell(spell)
            h.spellcasting["slots"][slot]["current"] -= 1
            rec = dice.roll(sp["heal"], purpose=f"a{n}: {sp['name']} on {c.name} after the fight", actor=h.id,
                            target=pid, extra_modifier=h.spell_mod if sp.get("add_mod") else 0)
            healed = c.heal(rec.total)
            c.remove_condition("prone")
            out.append({"id": f"a{n}", "who": h.id, "target": pid, "kind": "healing", "spell": spell,
                        "what": f"{h.name.split()[0]} - {sp['name']}", "result": "SUCCESS",
                        "means": f"{c.name.split()[0]} wakes with {healed['hp_after']} HP.",
                        "_roll": dict(rec.to_dict(), kind="dice")})
        elif best:
            h = best[1]
            c.stable = True
            out.append({"id": f"a{n}", "who": h.id, "target": pid, "kind": "stabilize", "spell": "spare_the_dying",
                        "what": f"{h.name.split()[0]} - Spare the Dying", "result": "SUCCESS",
                        "means": f"{c.name.split()[0]} is stable but unconscious (1 HP after 1d4 hours).",
                        "_roll": None})
        elif healers:
            h = max(healers, key=lambda x: x.skill_bonus("medicine"))
            rec = ability_check(h, dice, skill="medicine", dc=10, purpose=f"a{n}: stabilise {c.name}")
            c.stable = bool(rec.success)
            out.append({"id": f"a{n}", "who": h.id, "target": pid, "kind": "medicine",
                        "what": f"{h.name.split()[0]} - Medicine", "result": "SUCCESS" if rec.success else "FAILURE",
                        "means": "stable" if rec.success else "still dying", "_roll": rec.to_dict()})
    for a in out:
        if a["_roll"] is None:
            a["_roll"] = {"kind": "none"}
    return out


def _roll_check(ch: dict, party: dict, dice: Dice):
    adv, dis = bool(ch.get("advantage")), bool(ch.get("disadvantage"))
    purpose = f"{ch['id']}: {ch['reason']}"[:120]
    if ch.get("group"):
        g = group_check([party[a] for a in ch["group"]], ch["skill"], ch["dc"], dice, purpose=purpose)
        best = max(g["rolls"], key=lambda r: r.total)
        return best, g["rolls"], g["success"], {"group": [{"who": r.actor, "total": r.total, "success": r.success}
                                                          for r in g["rolls"]], "passed": g["passed"]}
    c = party[ch["actor"]]
    con = ch.get("contest")
    if con:
        other = party[con["actor"]] if con.get("actor") else monster_from_data(con["monster"], "opponent")
        if con.get("passive"):
            dc = other.passive(con.get("skill", "perception"))
            r = ability_check(c, dice, ability=ch.get("ability"), skill=ch.get("skill"), dc=dc, advantage=adv,
                              disadvantage=dis, purpose=purpose)
            return r, [r], bool(r.success), {"against": f"passive {con.get('skill', 'perception')} {dc}"}
        res = contest(c, ch["skill"], other, con["skill"], dice, purpose=purpose)
        res["a"].dc = res["b"].total
        res["a"].success = res["winner"] == c.id
        return res["a"], [res["a"], res["b"]], res["winner"] == c.id, {"against": f"{con['skill']} {res['b'].total}"}
    if ch.get("save"):
        r = saving_throw(c, dice, ch["ability"], ch["dc"], advantage=adv, disadvantage=dis, purpose=purpose)
    else:
        r = ability_check(c, dice, ability=ch.get("ability"), skill=ch.get("skill"), dc=ch["dc"], advantage=adv,
                          disadvantage=dis, purpose=purpose)
    return r, [r], bool(r.success), {}


def _fight(enc: dict, map_id: str, party: dict, sheets: dict, dice: Dice) -> dict:
    fighters = []
    for pid, xy in enc["party_at"].items():
        party[pid].pos = tuple(xy[:2])
        fighters.append(party[pid])
    kinds, names, nonlethal = {}, {}, set()
    for e in enc["enemies"]:
        m = monster_from_data(e["kind"], e["id"], pos=tuple(e["at"][:2]), name=e.get("name"),
                              nonlethal=bool(e.get("nonlethal")))
        fighters.append(m)
        kinds[e["id"]] = e.get("sprite", e["kind"])
        names[e["id"]] = e.get("name") or data.monsters()[e["kind"]]["name"].replace("Goblin Warrior", "Goblin")
        if e.get("nonlethal"):
            nonlethal.add(e["id"])
    for pid in party:
        names[pid] = _name(sheets, pid)
    encounter = Encounter(fighters, dice, name=enc["name"], occupied_extra=blocked_squares(map_id),
                          options=enc.get("options") or {})
    result = encounter.run(simple_policy)
    types = {(c.id, a.id): a.type for c in encounter.creatures.values() for a in c.attacks}
    cues = battle_cues(result, kinds=kinds, names=names, attack_types=types, music="battle", origin=(0, 0))
    for cue in cues:
        if cue["op"] == "battle_faint" and cue["actor"] in nonlethal:
            cue["pc"] = True          # lies down instead of vanishing: still on the map afterwards
            cue["nonlethal"] = True
    for pid in party:  # party creatures carry their HP and conditions into the next scenes
        party[pid] = encounter.creatures[pid]
    end_state = {c.id: {"hp": c.hp, "down": c.hp <= 0, "dead": c.dead, "pos": list(c.pos)}
                 for c in encounter.creatures.values()}
    for eid in nonlethal:
        if end_state[eid]["down"]:
            end_state[eid]["note"] = "knocked out, alive (nonlethal)"
    reasons = (enc.get("options") or {}).get("tactics", 1) >= 2
    return {"result": result, "cues": cues, "actions": action_log(cues, names, reasons), "end_state": end_state,
            "names": names, "kinds": kinds}


def action_log(cues: list[dict], names: dict, reasons: bool = False) -> list[str]:
    """Numbered actions (attacks, spells, healing) with the in-between moments
    unnumbered, so the writer can place narration "after action N". ``reasons`` (tactics 2) also says
    why a roll had advantage or disadvantage (flanking, pack tactics, long range...)."""
    out, n, rnd = [], 0, 1

    def nm(x):
        return names.get(x, x)

    for c in cues:
        op = c["op"]
        if op == "initiative":
            out.append("Initiative: " + ", ".join(f"{nm(o['id'])} {o['total']}" for o in c["order"]))
        elif op == "battle_turn":
            rnd = c.get("round", rnd)
        elif op in ("battle_attack", "battle_cast"):
            n += 1
            if op == "battle_attack":
                res = ("CRIT " if c.get("critical") else "") + (f"HIT for {c['damage']}" if c["hit"] else "MISS")
                if c.get("sneak_attack"):
                    res += " (sneak attack)"
                roll = c.get("roll") or {}
                if reasons and roll.get("advantage") in ("advantage", "disadvantage"):
                    sign = "+" if roll["advantage"] == "advantage" else "-"
                    why = [n[1:] for n in roll.get("notes", []) if n.startswith(sign)]
                    res += f" ({roll['advantage']}" + (f": {', '.join(why)})" if why else ")")
                hp = f", {nm(c['target'])} at {c['hp_after']} HP" if c["hit"] else ""
                out.append(f"{n}. [round {rnd}] {c['label']} -> {nm(c['target'])}: {res}{hp}")
            else:
                parts = []
                for r in c["results"]:
                    bits = []
                    if r.get("damage"):
                        bits.append(f"{r['damage']} dmg")
                    if r.get("heal"):
                        bits.append(f"+{r['heal']} HP")
                    if r.get("saved") is not None:
                        bits.append("saved" if r["saved"] else "failed save")
                    if r.get("hit") is not None:
                        bits.append("hit" if r["hit"] else "miss")
                    if r.get("revived"):
                        bits.append("back on their feet")
                    if r.get("effect"):
                        bits.append(r["effect"])
                    parts.append(f"{nm(r['target'])} {' '.join(bits)}".strip())
                out.append(f"{n}. [round {rnd}] {c['label']}: " + "; ".join(parts))
        elif op == "battle_move":
            out.append(f"   - {nm(c['actor'])} moves {5 * (len(c['path']) - 1)} ft")
        elif op == "battle_faint":
            out.append(f"   - {nm(c['actor'])} " + ("is knocked out (alive)" if c.get("nonlethal") else
                                                    "drops to 0 HP" if c.get("pc") else "falls"))
        elif op == "battle_note":
            out.append(f"   - {nm(c['actor'])}: {c['text']}")
        elif op == "roll":
            out.append(f"   - {c['label']}: {c['line']}")
        elif op == "battle_end":
            out.append(f"END: {c['result']}, {c.get('xp', 0)} XP")
    return out


def check_roll_cues(res: Resolution, plan: dict, sheets: dict) -> dict[str, list[dict]]:
    """Dice-tray cues for each on-screen check (one per roll; group checks show each member)."""
    out = {}
    checks = {ch["id"]: ch for sc in plan["scenes"] for ch in sc.get("checks", [])}
    aftermath = {a["id"]: a for a in res.outcomes.get("aftermath", [])}
    for cid, rolls in res.check_rolls.items():
        if cid in aftermath:
            a = aftermath[cid]
            r = rolls[0]
            cues = []
            if r.get("kind") != "none":
                line = f"{r['notation']} ({', '.join(map(str, r['kept']))})" + \
                       (f" + {r['modifier']}" if r.get("modifier") else "") + f" = {r['total']}"
                if a["kind"] == "healing":
                    line += " HP"
                cues.append({"op": "roll", "roll": r, "label": a["what"], "line": line})
            if a["kind"] in ("healing",):
                cues.append({"op": "battle_revive", "actor": a["target"]})
            out[cid] = cues
            continue
        ch = checks[cid]
        cues = []
        for r in rolls:
            label = _check_label(sheets, ch)
            if ch.get("group") or ch.get("contest"):
                skill = ch.get("skill") or ""
                con = ch.get("contest") or {}
                if con and r["actor"] != ch["actor"]:  # the opponent rolls their own skill
                    skill = con.get("skill") or skill
                label = f"{_name(sheets, r['actor']) if r['actor'] in sheets else r['actor'].title()} - " \
                        f"{skill.replace('_', ' ').title()}"
            cues.append({"op": "roll", "roll": r, "label": label,
                         "line": _line(r, "SUCCESS", "FAIL", "DC") if r.get("dc") is not None else _line(r)})
        out[cid] = cues
    return out


# -------------------------------------------------------------- proposals
LANTERN_STATES = ("lit", "flicker", "dead")
HOOK_STATES = ("dormant", "planted", "active", "resolved")


def apply_proposals(plan: dict, results: dict, sheets: dict, world: dict, dice: Dice | None = None,
                    night: list | None = None) -> list[dict]:
    """``dice`` and ``night`` serve camps and travel (production/features.json "camps"): their rolls go in
    the episode's log and what happened overnight goes to the writer as ``outcomes.nights``."""
    eid = plan["episode_id"]
    camps = features.enabled("camps", eid) and dice is not None
    log = []
    for p in plan.get("state_proposals", []):
        entry = dict(p)
        cond = p.get("if")
        if cond:
            ref, _, want = cond.partition(".")
            if results.get(ref) != want:
                entry.update(applied=False, why=f"condition {cond} not met ({ref} was {results.get(ref)})")
                log.append(entry)
                continue
        try:
            if camps and p["type"] in ("rest", "travel"):
                rep = _apply_camp(p, eid, sheets, world, dice)
                if night is not None and rep:
                    night.append(rep)
            else:
                _apply_one(p, eid, sheets, world)
            entry["applied"] = True
        except (KeyError, ValueError, TypeError) as exc:
            entry.update(applied=False, why=f"rejected: {exc}")
        log.append(entry)
    world.setdefault("flags", {})["series_started"] = True
    for sc in plan["scenes"]:  # everyone on screen has now been seen
        for c in sc["cast"]:
            nid = "npc." + c.get("sprite", c["id"]).replace("_", "-")
            if nid in world["npcs"]:
                n = world["npcs"][nid]
                n["first_seen"] = n.get("first_seen") or eid
                n["last_seen"] = eid
                if n["status"] == "unmet":
                    n["status"] = "alive"
    return log


def _apply_one(p: dict, eid: str, sheets: dict, world: dict) -> None:
    t = p["type"]
    if t == "lantern":
        if p["state"] not in LANTERN_STATES:
            raise ValueError(f"lantern state {p['state']!r}")
        if not p["id"].startswith("lantern_road.") and p["id"] not in world["lanterns"]:
            raise ValueError(f"unknown lantern {p['id']}")
        world["lanterns"][p["id"]] = p["state"]
    elif t == "npc":
        n = world["npcs"].setdefault(p["id"], {"status": "alive", "attitude": "indifferent", "location": None,
                                               "first_seen": eid, "last_seen": eid, "notes": []})
        if not p["id"].startswith("npc."):
            raise ValueError("npc ids start with 'npc.'")
        for k in ("status", "attitude", "location"):
            if k in p:
                n[k] = p[k]
        if p.get("name"):
            n["name"] = p["name"]
        if "name_known" in p:  # False: the viewers have met them but not heard their name yet
            n["name_known"] = bool(p["name_known"])
        if p.get("note"):
            n["notes"].append(p["note"])
        n["first_seen"] = n.get("first_seen") or eid
        n["last_seen"] = eid
    elif t == "quest":
        q = next((q for q in world["quests"] if q["id"] == p["id"]), None)
        if q is None:
            q = {"id": p["id"], "title": p["title"], "status": "active", "giver": p.get("giver"), "reward_cp": 0,
                 "objectives": []}
            world["quests"].append(q)
        for k in ("title", "status", "giver", "reward_cp"):
            if k in p:
                q[k] = p[k]
        q["objectives"] += [o for o in p.get("objectives", []) if o not in q["objectives"]]
    elif t == "hook":
        h = next(h for h in world["hooks"] if h["id"] == p["id"])
        if p.get("status", "planted") not in HOOK_STATES:
            raise ValueError(f"hook status {p.get('status')!r}")
        h["status"] = p.get("status", "planted")
        h["planted_in"] = h.get("planted_in") or eid
    elif t == "bond":
        b = next(b for b in world["party"]["bonds"] if {b["a"], b["b"]} == {p["a"], p["b"]})
        for k in ("trust", "tension", "romance"):
            d = int(p.get(k, 0))
            if abs(d) > 1:
                raise ValueError(f"bond {k} may move by at most 1 per episode")
            b[k] = max(0, min(10, b[k] + d))
        if p.get("note"):
            b["notes"].append(f"{eid}: {p['note']}")
    elif t == "flag":
        world.setdefault("flags", {})[p["id"]] = p.get("value", True)
    elif t == "faction":
        f = world["factions"][p["id"]]
        d = int(p.get("reputation_delta", 0))
        if abs(d) > 1:
            raise ValueError("reputation may move by at most 1 per episode")
        f["reputation"] += d
        if "known_to_party" in p:
            f["known_to_party"] = bool(p["known_to_party"])
        if p.get("note"):
            f["notes"].append(p["note"])
    elif t == "gold":
        cp = int(p["cp"])
        if abs(cp) > 10000:
            raise ValueError("gold changes above 100 gp need a human")
        if p.get("to", "party") == "party":
            world["party"]["shared_money_cp"] = max(0, world["party"]["shared_money_cp"] + cp)
        else:
            s = sheets[p["to"]]
            s["money_cp"] = max(0, s.get("money_cp", 0) + cp)
    elif t == "item":
        holder, qty = p.get("holder", "party"), int(p.get("qty", 1))
        if holder == "party":
            inv = world["party"]["shared_inventory"]
        else:
            inv = sheets[holder].setdefault("inventory", [])
        it = next((i for i in inv if i["id"] == p["id"]), None)
        if it is None:
            inv.append({"id": p["id"], "qty": qty, **({"name": p["name"]} if p.get("name") else {})})
        else:
            it["qty"] += qty
        inv[:] = [i for i in inv if i["qty"] > 0]
    elif t == "location":
        world["location"].update({k: p[k] for k in ("id", "map", "region", "unlight") if k in p})
    elif t == "clock":
        if "time_of_day" in p:
            world["clock"]["time_of_day"] = clock_time(p["time_of_day"])
        _advance_days(world["clock"], int(p.get("advance_days", 0)))
    elif t == "rest":
        from ..progression import long_rest, short_rest
        from ..state import character_from_sheet, sheet_from_character
        if p.get("kind", "long") == "long":
            for cid in list(sheets):
                c = character_from_sheet(sheets[cid])
                long_rest(c)
                sheets[cid] = sheet_from_character(c)
            if p.get("overnight", True):
                _advance_days(world["clock"], 1)
                world["clock"]["time_of_day"] = clock_time(p.get("wake", "morning"))
        elif p["kind"] == "short":
            for cid in list(sheets):
                c = character_from_sheet(sheets[cid])
                short_rest(c, Dice(f"{eid}-short-rest-{cid}"), hit_dice_to_spend=0)
                sheets[cid] = sheet_from_character(c)
        else:
            raise ValueError(f"rest kind {p['kind']!r}")
    elif t == "xp":
        amount = int(p["amount"])
        if not 0 <= amount <= 1000:
            raise ValueError("xp award out of range")
        for s in sheets.values():
            s["xp"] = s.get("xp", 0) + amount
    else:
        raise ValueError(f"unsupported proposal type {t!r}")


def _eat(sheets: dict, world: dict, meals: int) -> dict:
    """Each party member eats ``meals`` rations: their own first, then the shared packs, then a friend's."""
    def stock(inv):
        return next((i for i in inv if i["id"] == "rations"), None)
    shared = world["party"].setdefault("shared_inventory", [])
    hungry = []
    for cid, s in sheets.items():
        if s["hp"]["current"] <= 0 and s.get("dead"):
            continue
        for _ in range(meals):
            for inv in [s.setdefault("inventory", []), shared] + [o.setdefault("inventory", []) for o in sheets.values()]:
                it = stock(inv)
                if it and it["qty"] > 0:
                    it["qty"] -= 1
                    break
            else:
                hungry.append(cid)
    for inv in [shared] + [s.get("inventory", []) for s in sheets.values()]:
        inv[:] = [i for i in inv if not (i["id"] == "rations" and i["qty"] <= 0)]
    left = sum(i["qty"] for inv in [shared] + [s.get("inventory", []) for s in sheets.values()]
               for i in inv if i["id"] == "rations")
    return {"meals_each": meals, "hungry": sorted(set(hungry)), "rations_left": left}


def _apply_camp(p: dict, eid: str, sheets: dict, world: dict, dice: Dice) -> dict | None:
    """Rests and travel from the episode where "camps" is on (bible 10 §5-6):

    * ``{"type": "rest", "kind": "long", "camp": {"site": "wild", "watches": [["brannoc"], ["tamsin", "oriel"]],
      "lantern_lit": true}}`` - a night in the open: everyone eats a ration, the Unlight rule applies where
      the location is deep or abyssal Unlight and no lantern burns at the camp (DC 12 Wisdom save or a level
      of Exhaustion), and the watch order goes to the writer. A long rest needs at least 1 HP.
    * ``{"type": "rest", "kind": "short"}`` - an hour's rest: anyone below half HP spends Hit Dice
      (rolled here, in the episode's log) until they are at half or out of dice.
    * ``{"type": "travel", "days": 3, "to": "loc.waystation-nine"}`` - days on the road: the clock moves,
      a ration a day each, and the party arrives rested (one long rest) unless ``"rest": false``.
    """
    from ..progression import long_rest, short_rest, unlight_rest_check
    from ..state import character_from_sheet, sheet_from_character
    t = p["type"]
    rep: dict = {"type": t}
    if t == "travel":
        days = int(p.get("days", 1))
        if not 1 <= days <= 30:
            raise ValueError("travel is 1-30 days")
        _advance_days(world["clock"], days)
        world["clock"]["time_of_day"] = clock_time(p.get("arrive", "evening"))
        if p.get("to"):
            world["location"]["id"] = p["to"]
        rep.update(days=days, to=p.get("to"), food=_eat(sheets, world, days))
        if p.get("rest", True):
            for cid in list(sheets):
                c = character_from_sheet(sheets[cid])
                if c.hp > 0:
                    long_rest(c)
                sheets[cid] = sheet_from_character(c)
        return rep
    kind = p.get("kind", "long")
    if kind == "short":
        healed = {}
        for cid in list(sheets):
            c = character_from_sheet(sheets[cid])
            hd = (c.sheet or {}).get("hit_dice", {})
            need = 0
            if c.hp > 0 and c.hp < c.max_hp // 2:
                avg = hd.get("die", 8) // 2 + 1 + c.mod("con")
                need = max(1, -(-(c.max_hp // 2 - c.hp) // max(1, avg)))
            r = short_rest(c, dice, hit_dice_to_spend=need)
            if r["healed"]:
                healed[cid] = {"hp": f"{c.hp}/{c.max_hp}", "hit_dice_spent": r["hit_dice_spent"]}
            sheets[cid] = sheet_from_character(c)
        rep.update(kind="short", healed=healed)
        return rep
    if kind != "long":
        raise ValueError(f"rest kind {kind!r}")
    camp = p.get("camp")
    zone = world.get("location", {}).get("unlight", "none")
    lantern = bool((camp or {}).get("lantern_lit", False))
    rested, unlight = [], []
    for cid in list(sheets):
        c = character_from_sheet(sheets[cid])
        if c.hp > 0:                         # SRD 5.2: a long rest needs at least 1 HP
            long_rest(c)
            rested.append(cid)
            if camp is not None:
                u = unlight_rest_check(c, dice, zone, lantern)
                if u.get("roll"):
                    unlight.append({"who": cid, "exhaustion_gained": u["exhaustion_gained"],
                                    "exhaustion": u["exhaustion"]})
        sheets[cid] = sheet_from_character(c)
    if p.get("overnight", True):
        _advance_days(world["clock"], 1)
        world["clock"]["time_of_day"] = clock_time(p.get("wake", "morning"))
    rep.update(kind="long", rested=rested)
    if camp is not None:
        rep.update(site=camp.get("site", "wild"), watches=camp.get("watches", []), lantern_lit=lantern,
                   unlight_zone=zone)
        if camp.get("site", "wild") not in ("inn", "town", "fort"):
            rep["food"] = _eat(sheets, world, 1)
        if unlight:
            rep["unlight"] = unlight
    return rep


CLOCK_TIMES = ("dawn", "morning", "noon", "afternoon", "dusk", "evening", "night", "midnight")  # world schema
CLOCK_ALIASES = {"day": "noon"}  # scene lighting presets that aren't clock values


def clock_time(value: str) -> str:
    v = CLOCK_ALIASES.get(value, value)
    if v not in CLOCK_TIMES:
        raise ValueError(f"time of day {value!r} (use one of {', '.join(CLOCK_TIMES)})")
    return v


def _advance_days(clock: dict, days: int) -> None:
    """30-day months, 12 months a year (bible 01 §6; the Hearthdays are not modelled yet)."""
    clock["day"] += days
    while clock["day"] > 30:
        clock["day"] -= 30
        clock["month"] += 1
        if clock["month"] > 12:
            clock["month"] = 1
            clock["year"] += 1


def _advance_series(plan: dict, world: dict) -> None:
    ep = int(plan["episode_id"][-3:])
    world["series"]["episode"] = world["series"].get("episode", 0) + 1
    world["series"]["episode_in_campaign"] = ep
