"""Creatures: party members, NPCs and monsters share one model."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import data
from .rules import INCAPACITATING, SKILLS, modifier


@dataclass
class Effect:
    """A temporary effect on a creature (Bless, Vex, Dodge, Shield...).

    ``expires`` is ``None`` (lasts until removed or rounds run out) or a tuple
    ``(when, creature_id, skip)`` where ``when`` is ``"start"`` or ``"end"`` of
    that creature's turn and ``skip`` is how many such boundaries to let pass
    first (used for "until the end of your next turn").
    """

    name: str
    source: str
    data: dict = field(default_factory=dict)
    expires: tuple[str, str, int] | None = None
    rounds_left: int | None = None
    concentration: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "data": self.data,
            "expires": list(self.expires) if self.expires else None,
            "rounds_left": self.rounds_left,
            "concentration": self.concentration,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Effect":
        exp = d.get("expires")
        return cls(d["name"], d["source"], d.get("data", {}), tuple(exp) if exp else None,
                   d.get("rounds_left"), d.get("concentration", False))


@dataclass
class Attack:
    id: str
    name: str
    type: str  # "melee" | "ranged"
    to_hit: int
    damage: str
    damage_type: str
    reach_ft: int = 5
    range: tuple[int, int] | None = None
    properties: tuple[str, ...] = ()
    mastery: str | None = None
    weapon_id: str | None = None
    ability: str | None = None
    damage_mod: int = 0  # already folded into ``damage`` for monsters; kept for the overlay
    extra_damage: tuple[tuple[str, str], ...] = ()
    extra_damage_if_advantage: str | None = None
    on_hit: dict | None = None
    is_weapon: bool = True
    thrown_mode: bool = False

    @property
    def finesse_or_ranged(self) -> bool:
        return "finesse" in self.properties or self.type == "ranged"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "type": self.type, "to_hit": self.to_hit,
            "damage": self.damage, "damage_type": self.damage_type, "reach_ft": self.reach_ft,
            "range": list(self.range) if self.range else None, "mastery": self.mastery,
        }


@dataclass
class Creature:
    id: str
    name: str
    kind: str  # "pc" | "npc" | "monster"
    team: str
    abilities: dict[str, int]
    max_hp: int
    hp: int
    proficiency: int = 2
    level: int = 0
    cr: str | None = None
    xp_value: int = 0
    temp_hp: int = 0
    size: str = "medium"
    speed: int = 30
    natural_ac: int | None = None  # monsters: AC from the stat block
    armor: str | None = None
    shield: bool = False
    ac_static_bonus: int = 0  # Defense fighting style, magic items
    save_profs: set[str] = field(default_factory=set)
    save_overrides: dict[str, int] = field(default_factory=dict)
    skill_profs: set[str] = field(default_factory=set)
    expertise: set[str] = field(default_factory=set)
    skill_overrides: dict[str, int] = field(default_factory=dict)
    resistances: set[str] = field(default_factory=set)
    immunities: set[str] = field(default_factory=set)
    vulnerabilities: set[str] = field(default_factory=set)
    condition_immunities: set[str] = field(default_factory=set)
    traits: set[str] = field(default_factory=set)
    feats: set[str] = field(default_factory=set)
    features: set[str] = field(default_factory=set)
    weapon_masteries: set[str] = field(default_factory=set)
    attacks: list[Attack] = field(default_factory=list)
    multiattack: list[str] = field(default_factory=list)
    extra_attacks: int = 0
    crit_range: int = 20
    sneak_attack_dice: int = 0
    char_class: str | None = None
    subclass: str | None = None
    spellcasting: dict | None = None
    resources: dict[str, dict] = field(default_factory=dict)
    conditions: dict[str, dict] = field(default_factory=dict)
    exhaustion: int = 0
    death_saves: dict[str, int] = field(default_factory=lambda: {"successes": 0, "failures": 0})
    stable: bool = False
    dead: bool = False
    concentration: str | None = None
    effects: list[Effect] = field(default_factory=list)
    pos: tuple[int, int] = (0, 0)
    heroic_inspiration: bool = False
    inventory: dict[str, int] = field(default_factory=dict)
    darkvision: int = 0
    passive_perception_override: int | None = None
    nonlethal: bool = False
    ai_role: str | None = None  # tactical role for the fallback AI (monsters)
    sheet: dict | None = None  # source sheet for PCs (written back by state.py)

    # ------------------------------------------------------------- numbers
    def mod(self, ability: str) -> int:
        return modifier(self.abilities[ability])

    def save_bonus(self, ability: str) -> int:
        if ability in self.save_overrides:
            return self.save_overrides[ability]
        bonus = self.mod(ability)
        if ability in self.save_profs:
            bonus += self.proficiency
        return bonus

    def skill_bonus(self, skill: str) -> int:
        if skill in self.skill_overrides:
            return self.skill_overrides[skill]
        bonus = self.mod(SKILLS[skill])
        if skill in self.expertise:
            bonus += 2 * self.proficiency
        elif skill in self.skill_profs:
            bonus += self.proficiency
        return bonus

    def passive(self, skill: str = "perception") -> int:
        if skill == "perception" and self.passive_perception_override is not None:
            return self.passive_perception_override
        return 10 + self.skill_bonus(skill)

    @property
    def initiative_bonus(self) -> int:
        bonus = self.mod("dex")
        if "alert" in self.feats:
            bonus += self.proficiency
        return bonus

    @property
    def spell_mod(self) -> int:
        if not self.spellcasting:
            return 0
        return self.mod(self.spellcasting["ability"])

    @property
    def spell_attack_bonus(self) -> int:
        return self.proficiency + self.spell_mod

    @property
    def spell_save_dc(self) -> int:
        return 8 + self.proficiency + self.spell_mod

    @property
    def ac(self) -> int:
        if self.natural_ac is not None and self.armor is None:
            base = self.natural_ac
        elif self.armor:
            arm = data.armor()[self.armor]
            dex = self.mod("dex")
            if arm["dex"] == "full":
                base = arm["base_ac"] + dex
            elif arm["dex"] == "max2":
                base = arm["base_ac"] + min(dex, 2)
            else:
                base = arm["base_ac"]
        else:
            base = 10 + self.mod("dex")
            mage = self.effect("mage_armor")
            if mage:
                base = max(base, mage.data.get("base_ac", 13) + self.mod("dex"))
        total = base + self.ac_static_bonus
        if self.shield:
            total += data.shield_bonus()
        for eff in self.effects:
            total += eff.data.get("ac_bonus", 0)
        return total

    @property
    def current_speed(self) -> int:
        if self.has_condition("grappled") or self.has_condition("restrained") or self.incapacitated:
            return 0
        speed = self.speed - 5 * self.exhaustion
        for eff in self.effects:
            speed -= eff.data.get("speed_penalty", 0)
        return max(0, speed)

    def cantrip_dice_multiplier(self) -> int:
        lvl = self.level or int((self.spellcasting or {}).get("caster_level", 1))
        return 1 + (lvl >= 5) + (lvl >= 11) + (lvl >= 17)

    # ----------------------------------------------------------- statuses
    def has_condition(self, name: str) -> bool:
        return name in self.conditions

    @property
    def incapacitated(self) -> bool:
        return any(c in self.conditions for c in INCAPACITATING)

    @property
    def conscious(self) -> bool:
        return not self.dead and self.hp > 0 and not self.has_condition("unconscious")

    @property
    def standing(self) -> bool:
        """Still in the fight: alive, above 0 HP."""
        return not self.dead and self.hp > 0

    def add_condition(self, name: str, source: str | None = None, **info: Any) -> bool:
        if name in self.condition_immunities:
            return False
        self.conditions[name] = {"source": source, **info}
        if name == "unconscious":
            self.conditions.setdefault("prone", {"source": source})
        return True

    def remove_condition(self, name: str) -> None:
        self.conditions.pop(name, None)

    def effect(self, name: str) -> Effect | None:
        for eff in self.effects:
            if eff.name == name:
                return eff
        return None

    def effects_named(self, name: str) -> list[Effect]:
        return [e for e in self.effects if e.name == name]

    def add_effect(self, eff: Effect) -> None:
        # Same-named effects from the same source don't stack (SRD).
        self.effects = [e for e in self.effects if not (e.name == eff.name and e.source == eff.source)]
        self.effects.append(eff)

    def remove_effects(self, predicate) -> list[Effect]:
        gone = [e for e in self.effects if predicate(e)]
        self.effects = [e for e in self.effects if not predicate(e)]
        return gone

    # ------------------------------------------------------------- damage
    def adjust_damage(self, amount: int, damage_type: str) -> tuple[int, str | None]:
        """Apply immunity, resistance and vulnerability (in that order)."""
        if amount <= 0:
            return 0, None
        if damage_type in self.immunities:
            return 0, "immune"
        note = None
        if damage_type in self.resistances:
            amount //= 2
            note = "resistant"
        if damage_type in self.vulnerabilities:
            amount *= 2
            note = "vulnerable" if note is None else "resistant+vulnerable"
        return amount, note

    def take_damage(self, amount: int, damage_type: str, critical: bool = False,
                    already_adjusted: bool = False) -> dict:
        """Apply damage. Returns a result dict for the event log.

        Party members (``kind == "pc"``) fall unconscious at 0 HP and suffer
        Death Save failures from further damage; massive damage (remaining
        damage >= max HP) kills outright. Monsters die at 0 HP unless marked
        ``nonlethal``.
        """
        hp_before = self.hp
        note = None
        if not already_adjusted:
            amount, note = self.adjust_damage(amount, damage_type)
        result = {
            "amount": amount, "type": damage_type, "note": note, "hp_before": hp_before,
            "temp_absorbed": 0, "dropped_to_zero": False, "died": False, "instant_death": False,
            "death_save_failures": 0,
        }
        if amount <= 0 or self.dead:
            result["hp_after"] = self.hp
            return result
        if self.temp_hp:
            absorbed = min(self.temp_hp, amount)
            self.temp_hp -= absorbed
            amount -= absorbed
            result["temp_absorbed"] = absorbed
        if amount <= 0:
            result["hp_after"] = self.hp
            return result

        if self.hp == 0:
            # Damage while at 0 HP.
            if amount >= self.max_hp:
                self._die(result, instant=True)
            else:
                fails = 2 if critical else 1
                self.stable = False
                self.death_saves["failures"] += fails
                result["death_save_failures"] = fails
                if self.death_saves["failures"] >= 3:
                    self._die(result)
            result["hp_after"] = self.hp
            return result

        remaining = amount - self.hp
        self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            result["dropped_to_zero"] = True
            if self.kind == "pc" or self.nonlethal:
                if self.kind == "pc" and remaining >= self.max_hp:
                    self._die(result, instant=True)
                else:
                    self.add_condition("unconscious", source="0hp")
                    self.death_saves = {"successes": 0, "failures": 0}
                    self.stable = self.kind != "pc"
            else:
                self._die(result)
        result["hp_after"] = self.hp
        return result

    def _die(self, result: dict, instant: bool = False) -> None:
        self.hp = 0
        self.dead = True
        self.stable = False
        self.concentration = None
        self.conditions.pop("unconscious", None)
        result["died"] = True
        result["instant_death"] = instant

    def heal(self, amount: int) -> dict:
        before = self.hp
        if self.dead or amount <= 0:
            return {"amount": 0, "hp_before": before, "hp_after": self.hp, "revived": False}
        self.hp = min(self.max_hp, self.hp + amount)
        revived = before == 0 and self.hp > 0
        if revived:
            self.remove_condition("unconscious")
            self.death_saves = {"successes": 0, "failures": 0}
            self.stable = False
        return {"amount": self.hp - before, "hp_before": before, "hp_after": self.hp, "revived": revived}

    def gain_temp_hp(self, amount: int) -> int:
        """Temporary HP don't stack; keep the higher value."""
        self.temp_hp = max(self.temp_hp, amount)
        return self.temp_hp

    # ------------------------------------------------------------ helpers
    def attack_by_id(self, attack_id: str) -> Attack:
        for a in self.attacks:
            if a.id == attack_id:
                return a
        raise KeyError(f"{self.id} has no attack {attack_id!r}")

    def knows_spell(self, spell_id: str) -> bool:
        if not self.spellcasting:
            return False
        sc = self.spellcasting
        return spell_id in sc.get("cantrips", []) or spell_id in sc.get("prepared", []) \
            or spell_id in sc.get("free_casts", {})

    def slots_available(self, level: int) -> int:
        if not self.spellcasting or level == 0:
            return 0
        slot = self.spellcasting.get("slots", {}).get(str(level))
        return slot["current"] if slot else 0

    def lowest_slot_at_least(self, level: int) -> int | None:
        if not self.spellcasting:
            return None
        for lvl in range(level, 10):
            if self.slots_available(lvl) > 0:
                return lvl
        return None

    def summary(self) -> dict:
        return {
            "id": self.id, "name": self.name, "team": self.team, "hp": self.hp, "max_hp": self.max_hp,
            "temp_hp": self.temp_hp, "ac": self.ac, "pos": list(self.pos), "conditions": sorted(self.conditions),
            "effects": [e.name for e in self.effects], "dead": self.dead, "stable": self.stable,
            "death_saves": dict(self.death_saves), "concentration": self.concentration,
        }
