"""Load and save state: character sheets, monsters, world and episode files."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from . import data
from .creature import Attack, Creature, Effect
from .rules import proficiency_bonus

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
PARTY_DIR = STATE_DIR / "party"
# The series start (level 1, 3 Emberfall 1047 AK). Live state moves on after each
# committed episode; tests, demos and the Episode 1 replay use this snapshot.
GENESIS_DIR = STATE_DIR / "genesis"
GENESIS_PARTY_DIR = GENESIS_DIR / "party"


def load_json(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, obj: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------- weapons
def _weapon_attacks(sheet: dict, abilities: dict, prof: int) -> list[Attack]:
    from .rules import modifier

    weapons = data.weapons()
    profs = set(sheet.get("weapon_proficiencies", []))
    masteries = set(sheet.get("weapon_masteries", []))
    attacks: list[Attack] = []
    for wid in sheet.get("equipment", {}).get("weapons", []):
        w = weapons[wid]
        proficient = w["category"] in profs or wid in profs
        str_mod, dex_mod = modifier(abilities["str"]), modifier(abilities["dex"])
        if "finesse" in w["properties"]:
            ability = "dex" if dex_mod >= str_mod else "str"
        elif w["type"] == "ranged":
            ability = "dex"
        else:
            ability = "str"
        mod = modifier(abilities[ability])
        to_hit = mod + (prof if proficient else 0)
        damage = f"{w['damage']}{mod:+d}" if mod else w["damage"]
        common = dict(
            name=w["name"], to_hit=to_hit, damage=damage, damage_type=w["damage_type"],
            properties=tuple(w["properties"]), mastery=w["mastery"] if wid in masteries else None,
            weapon_id=wid, ability=ability, damage_mod=mod,
        )
        if w["type"] == "melee":
            attacks.append(Attack(id=wid, type="melee", reach_ft=10 if "reach" in w["properties"] else 5, **common))
            if "thrown" in w["properties"]:
                attacks.append(Attack(id=f"{wid}:thrown", type="ranged", range=tuple(w["range"]),
                                      thrown_mode=True, **common))
        else:
            attacks.append(Attack(id=wid, type="ranged", range=tuple(w["range"]), **common))
    # Unarmed Strike (SRD 5.2): 1 + Str modifier bludgeoning, proficient.
    str_mod = modifier(abilities["str"])
    attacks.append(Attack(id="unarmed", name="Unarmed Strike", type="melee", to_hit=str_mod + prof,
                          damage=str(max(0, 1 + str_mod)), damage_type="bludgeoning", is_weapon=False,
                          ability="str"))
    return attacks


# --------------------------------------------------------------- characters
def character_from_sheet(sheet: dict, team: str = "party") -> Creature:
    cls = data.classes()[sheet["class"]]
    spc = data.species()[sheet["species"]]
    level = sheet["level"]
    prof = proficiency_bonus(level)
    abilities = dict(sheet["abilities"])
    eq = sheet.get("equipment", {})
    armor = eq.get("armor")
    feats = set(sheet.get("feats", []))
    features = set(sheet.get("features", []))
    subclass = sheet.get("subclass")

    extra_attacks = data.column(cls["columns"].get("extra_attacks", {}), level, 0)
    sneak = data.column(cls["columns"].get("sneak_attack_dice", {}), level, 0)
    crit_range = 20
    if subclass and subclass in cls.get("subclasses", {}):
        crit_range = data.column(cls["subclasses"][subclass].get("columns", {}).get("crit_range", {}), level, 20)

    spellcasting = copy.deepcopy(sheet.get("spellcasting")) if sheet.get("spellcasting") else None

    c = Creature(
        id=sheet["id"], name=sheet["name"], kind="pc", team=team,
        abilities=abilities, max_hp=sheet["hp"]["max"], hp=sheet["hp"]["current"], temp_hp=sheet["hp"].get("temp", 0),
        proficiency=prof, level=level, size=sheet.get("size", "medium" if sheet["species"] in ("dwarf", "elf", "human") else "small"),
        speed=sheet.get("speed", spc["speed"]), armor=armor, shield=bool(eq.get("shield")),
        ac_static_bonus=(1 if ("fighting_style_defense" in feats and armor) else 0) + sheet.get("ac_bonus", 0),
        save_profs=set(cls["saves"]), skill_profs=set(sheet.get("skill_proficiencies", [])),
        expertise=set(sheet.get("expertise", [])),
        resistances=set(sheet.get("resistances", spc.get("resistances", []))),
        immunities=set(sheet.get("immunities", [])), vulnerabilities=set(sheet.get("vulnerabilities", [])),
        condition_immunities=set(sheet.get("condition_immunities", [])),
        traits=set(spc.get("traits", [])) | set(sheet.get("traits", [])),
        feats=feats, features=features, weapon_masteries=set(sheet.get("weapon_masteries", [])),
        attacks=_weapon_attacks(sheet, abilities, prof), extra_attacks=extra_attacks, crit_range=crit_range,
        sneak_attack_dice=sneak, char_class=sheet["class"], subclass=subclass, spellcasting=spellcasting,
        resources=copy.deepcopy(sheet.get("resources", {})), conditions=dict(sheet.get("conditions", {})),
        exhaustion=sheet.get("exhaustion", 0), death_saves=dict(sheet.get("death_saves", {"successes": 0, "failures": 0})),
        stable=sheet.get("stable", False), dead=sheet.get("dead", False), concentration=sheet.get("concentration"),
        effects=[Effect.from_dict(e) for e in sheet.get("effects", [])],
        heroic_inspiration=sheet.get("heroic_inspiration", False),
        inventory={i["id"]: i["qty"] for i in sheet.get("inventory", [])},
        darkvision=sheet.get("darkvision", spc.get("darkvision", 0)), sheet=copy.deepcopy(sheet),
    )
    return c


def sheet_from_character(c: Creature) -> dict:
    """Write a creature's mutable state back into its sheet (returns a new dict)."""
    if c.sheet is None:
        raise ValueError("Only party members built from a sheet can be written back")
    s = copy.deepcopy(c.sheet)
    s["level"] = c.level
    s["hp"] = {"max": c.max_hp, "current": c.hp, "temp": c.temp_hp}
    s["conditions"] = c.conditions
    s["exhaustion"] = c.exhaustion
    s["death_saves"] = c.death_saves
    s["stable"] = c.stable
    s["dead"] = c.dead
    s["concentration"] = c.concentration
    s["resources"] = c.resources
    s["heroic_inspiration"] = c.heroic_inspiration
    s["effects"] = [e.to_dict() for e in c.effects if e.rounds_left is None or e.rounds_left > 10]
    if c.spellcasting:
        s["spellcasting"] = c.spellcasting
    s["inventory"] = [{"id": k, "qty": v} for k, v in sorted(c.inventory.items()) if v > 0]
    return s


def load_party(directory: str | Path = PARTY_DIR) -> dict[str, Creature]:
    party = {}
    for path in sorted(Path(directory).glob("*.json")):
        sheet = load_json(path)
        party[sheet["id"]] = character_from_sheet(sheet)
    return party


# ----------------------------------------------------------------- monsters
def monster_from_data(monster_id: str, instance_id: str | None = None, team: str = "enemies",
                      pos: tuple[int, int] = (0, 0), name: str | None = None, nonlethal: bool = False) -> Creature:
    m = data.monsters()[monster_id]
    attacks = []
    for a in m["attacks"]:
        rng = tuple(a["range"]) if a.get("range") else None
        attacks.append(Attack(
            id=a["id"], name=a["name"], type=a["type"], to_hit=a["to_hit"], damage=a["damage"],
            damage_type=a["damage_type"], reach_ft=a.get("reach_ft", 5), range=rng,
            extra_damage=tuple(tuple(x) for x in a.get("extra_damage", [])),
            extra_damage_if_advantage=a.get("extra_damage_if_advantage"), on_hit=a.get("on_hit"),
            properties=tuple(a.get("properties", ())),
        ))
        # A melee weapon with a range can also be thrown.
        if a["type"] == "melee" and rng:
            attacks.append(Attack(
                id=f"{a['id']}:thrown", name=a["name"], type="ranged", to_hit=a["to_hit"], damage=a["damage"],
                damage_type=a["damage_type"], range=rng, thrown_mode=True,
                extra_damage=tuple(tuple(x) for x in a.get("extra_damage", [])),
                extra_damage_if_advantage=a.get("extra_damage_if_advantage"),
            ))
    senses = m.get("senses", {})
    return Creature(
        id=instance_id or monster_id, name=name or m["name"], kind="monster", team=team,
        abilities=dict(m["abilities"]), max_hp=m["hp"], hp=m["hp"], proficiency=m.get("proficiency", 2),
        cr=str(m["cr"]), xp_value=m.get("xp", 0), size=m.get("size", "medium"), speed=m.get("speed", 30),
        natural_ac=m["ac"], save_overrides=dict(m.get("saves", {})), skill_overrides=dict(m.get("skills", {})),
        resistances=set(m.get("resistances", [])), immunities=set(m.get("immunities", [])),
        vulnerabilities=set(m.get("vulnerabilities", [])), condition_immunities=set(m.get("condition_immunities", [])),
        traits=set(m.get("traits", [])), attacks=attacks, multiattack=list(m.get("multiattack", [])),
        pos=tuple(pos), darkvision=senses.get("darkvision", 0),
        passive_perception_override=senses.get("passive_perception"), nonlethal=nonlethal,
        ai_role=m.get("ai"),
    )
