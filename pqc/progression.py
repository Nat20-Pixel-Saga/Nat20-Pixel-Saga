"""Levelling, XP and rests (SRD 5.2, milestone levelling with fixed HP)."""
from __future__ import annotations

from . import data
from .checks import saving_throw
from .creature import Creature
from .dice import Dice
from .rules import proficiency_bonus

# Feature flags the engine reads, keyed by (class, subclass or None, level).
ENGINE_FEATURES = {
    ("fighter", None, 2): ["action_surge"],
    ("rogue", None, 2): ["cunning_action"],
    ("rogue", None, 5): ["uncanny_dodge"],
    ("rogue", None, 7): ["evasion", "reliable_talent"],
    ("wizard", "evoker", 3): ["potent_cantrip"],
    ("cleric", "life", 3): ["disciple_of_life"],
}


def level_for_xp(xp: int) -> int:
    level = 1
    for i, threshold in enumerate(data.xp_thresholds(), start=1):
        if xp >= threshold:
            level = i
    return level


def hp_gain_fixed(hit_die: int) -> int:
    """Fixed HP per level (SRD option): half the die + 1."""
    return hit_die // 2 + 1


def level_up(sheet: dict, subclass: str | None = None) -> dict:
    """Advance a character sheet by one level. Returns a report dict.

    Ability Score Improvements and new spells are *not* chosen here; they are
    recorded as ``pending_choices`` for the planner / dossier plan to resolve
    with :func:`apply_ability_increase` and the spell lists.
    """
    cls_id = sheet["class"]
    cls = data.classes()[cls_id]
    old = sheet["level"]
    if old >= 20:
        raise ValueError("Already level 20")
    new = old + 1
    report = {"id": sheet["id"], "from": old, "to": new, "gains": [], "pending_choices": []}

    if new == cls["subclass_level"]:
        if not subclass and not sheet.get("subclass"):
            raise ValueError(f"Level {new} requires a subclass choice")
        sheet["subclass"] = subclass or sheet.get("subclass")
        report["gains"].append(f"Subclass: {sheet['subclass']}")
    sub = sheet.get("subclass")

    con_mod = (sheet["abilities"]["con"] - 10) // 2
    gain = hp_gain_fixed(cls["hit_die"]) + con_mod + data.species()[sheet["species"]].get("hp_per_level", 0)
    gain = max(1, gain)
    sheet["hp"]["max"] += gain
    sheet["hp"]["current"] += gain
    sheet["hit_dice"]["max"] = new
    sheet["hit_dice"]["current"] = min(new, sheet["hit_dice"]["current"] + 1)
    report["gains"].append(f"+{gain} max HP")

    sheet["level"] = new
    report["proficiency_bonus"] = proficiency_bonus(new)

    names = list(cls["features"].get(str(new), []))
    if sub and sub in cls.get("subclasses", {}):
        names += cls["subclasses"][sub]["features"].get(str(new), [])
    report["gains"] += names
    sheet.setdefault("feature_names", []).extend(names)

    for (c, s, lvl), flags in ENGINE_FEATURES.items():
        if c == cls_id and lvl == new and (s is None or s == sub):
            for flag in flags:
                if flag not in sheet.setdefault("features", []):
                    sheet["features"].append(flag)

    cols = cls["columns"]
    res = sheet.setdefault("resources", {})
    if "second_wind_uses" in cols:
        n = data.column(cols["second_wind_uses"], new)
        res["second_wind"] = {"max": n, "current": min(n, res.get("second_wind", {}).get("current", 0) + 1),
                              "recharge": "long", "short_rest_regain": 1}
    if "action_surge_uses" in cols and data.column(cols["action_surge_uses"], new):
        n = data.column(cols["action_surge_uses"], new)
        res["action_surge"] = {"max": n, "current": n, "recharge": "short"}
    if "indomitable_uses" in cols and data.column(cols["indomitable_uses"], new):
        n = data.column(cols["indomitable_uses"], new)
        res["indomitable"] = {"max": n, "current": n, "recharge": "long"}
    if "channel_divinity_uses" in cols and data.column(cols["channel_divinity_uses"], new):
        n = data.column(cols["channel_divinity_uses"], new)
        res["channel_divinity"] = {"max": n, "current": n, "recharge": "long", "short_rest_regain": 1}

    sc = sheet.get("spellcasting")
    if sc and cls.get("spellcasting", {}) and cls["spellcasting"]["type"] == "full":
        table = data.full_caster_slots(new)
        old_slots = sc.get("slots", {})
        sc["slots"] = {}
        for i, n in enumerate(table, start=1):
            prev = old_slots.get(str(i), {"max": 0, "current": 0})
            sc["slots"][str(i)] = {"max": n, "current": prev["current"] + (n - prev["max"])}
        report["spell_slots"] = table
        cantrips = data.column(cols.get("cantrips_known", {}), new)
        prepared = data.column(cols.get("prepared_spells", {}), new)
        report["cantrips_known"] = cantrips
        report["prepared_spells"] = prepared
        if prepared > data.column(cols.get("prepared_spells", {}), old):
            report["pending_choices"].append(f"prepare up to {prepared} spells")
        if cantrips > data.column(cols.get("cantrips_known", {}), old):
            report["pending_choices"].append("learn a cantrip")
        if cls_id == "wizard":
            report["pending_choices"].append("add 2 wizard spells to the spellbook")
    if new in cls["asi_levels"]:
        report["pending_choices"].append("Ability Score Improvement (or a general feat)")
    if new == cls.get("epic_boon_level"):
        report["pending_choices"].append("Epic Boon feat")
    sheet.setdefault("level_history", []).append({"level": new, "hp_gain": gain, "gains": report["gains"]})
    return report


def apply_ability_increase(sheet: dict, increases: dict[str, int]) -> None:
    """Apply an ASI: +2 to one ability or +1 to two, max 20."""
    if sum(increases.values()) != 2 or any(v not in (1, 2) for v in increases.values()):
        raise ValueError("An ASI is +2 to one ability or +1 to two abilities")
    for ab, v in increases.items():
        if sheet["abilities"][ab] + v > 20:
            raise ValueError(f"{ab} would exceed 20")
    old_con = sheet["abilities"]["con"]
    for ab, v in increases.items():
        sheet["abilities"][ab] += v
    # A Con modifier increase raises max HP retroactively (SRD).
    delta = (sheet["abilities"]["con"] - 10) // 2 - (old_con - 10) // 2
    if delta:
        sheet["hp"]["max"] += delta * sheet["level"]
        sheet["hp"]["current"] += delta * sheet["level"]


# ------------------------------------------------------------------- rests
def short_rest(c: Creature, dice: Dice, hit_dice_to_spend: int = 0) -> dict:
    """Short rest: spend Hit Point Dice, recover short-rest resources."""
    report = {"id": c.id, "healed": 0, "hit_dice_spent": 0, "rolls": [], "recovered": []}
    hd = c.sheet["hit_dice"] if c.sheet else None
    if hd and c.hp > 0:
        for _ in range(min(hit_dice_to_spend, hd["current"])):
            if c.hp >= c.max_hp:
                break
            rec = dice.roll(f"1d{hd['die']}", purpose="hit die", actor=c.id, extra_modifier=c.mod("con"))
            out = c.heal(max(0, rec.total))
            hd["current"] -= 1
            report["healed"] += out["amount"]
            report["hit_dice_spent"] += 1
            report["rolls"].append(rec.id)
    for name, r in c.resources.items():
        if r.get("recharge") == "short":
            r["current"] = r["max"]
            report["recovered"].append(name)
        elif r.get("short_rest_regain"):
            r["current"] = min(r["max"], r["current"] + r["short_rest_regain"])
            report["recovered"].append(f"{name} (+{r['short_rest_regain']})")
    return report


def arcane_recovery(c: Creature, slots: dict[int, int]) -> dict:
    """Wizard Arcane Recovery on a short rest: slots totalling <= ceil(level/2), none 6th+."""
    res = c.resources.get("arcane_recovery")
    if not res or res["current"] <= 0:
        raise ValueError("Arcane Recovery already used today")
    budget = (c.level + 1) // 2
    if sum(lvl * n for lvl, n in slots.items()) > budget or any(lvl >= 6 for lvl in slots):
        raise ValueError(f"Arcane Recovery budget is {budget} slot levels, none 6th or higher")
    for lvl, n in slots.items():
        s = c.spellcasting["slots"][str(lvl)]
        if s["current"] + n > s["max"]:
            raise ValueError(f"Can't exceed max level-{lvl} slots")
        s["current"] += n
    res["current"] -= 1
    return {"id": c.id, "recovered_slots": slots}


def long_rest(c: Creature) -> dict:
    """Long rest: all HP, all Hit Point Dice, all slots and resources, -1 Exhaustion."""
    if c.dead:
        return {"id": c.id, "note": "dead"}
    c.hp = c.max_hp
    c.temp_hp = 0
    c.remove_condition("unconscious")
    c.remove_condition("prone")          # after eight hours everyone gets up, including the once-downed
    c.death_saves = {"successes": 0, "failures": 0}
    c.stable = False
    if c.sheet:
        c.sheet["hit_dice"]["current"] = c.sheet["hit_dice"]["max"]
    for r in c.resources.values():
        r["current"] = r["max"]
    if c.spellcasting:
        for s in c.spellcasting.get("slots", {}).values():
            s["current"] = s["max"]
        for f in c.spellcasting.get("free_casts", {}).values():
            f["current"] = f["max"]
    c.exhaustion = max(0, c.exhaustion - 1)
    c.effects = [e for e in c.effects if e.rounds_left is None and e.name not in ("mage_armor",)]
    c.concentration = None
    if "resourceful" in c.traits:
        c.heroic_inspiration = True
    return {"id": c.id, "hp": c.hp, "exhaustion": c.exhaustion, "heroic_inspiration": c.heroic_inspiration}


def unlight_rest_check(c: Creature, dice: Dice, zone: str, lantern_nearby: bool) -> dict:
    """Original rule (bible 10 §6): resting in deep Unlight may cause Exhaustion."""
    if zone not in ("deep", "abyssal") or lantern_nearby:
        return {"id": c.id, "exhaustion_gained": 0}
    rec = saving_throw(c, dice, "wis", 12, purpose="Unlight rest")
    gained = 0 if rec.success else 1
    c.exhaustion += gained
    if c.exhaustion >= 6:
        c.dead = True
        c.hp = 0
    return {"id": c.id, "roll": rec.id, "exhaustion_gained": gained, "exhaustion": c.exhaustion}
