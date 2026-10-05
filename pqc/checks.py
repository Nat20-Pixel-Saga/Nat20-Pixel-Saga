"""Ability checks, saving throws, death saves, contests and group checks."""
from __future__ import annotations

from .creature import Creature
from .dice import Dice, RollRecord
from .rules import SKILLS

AUTO_FAIL_SAVE_CONDITIONS = {"paralyzed", "petrified", "stunned", "unconscious"}


def _luck(c: Creature) -> bool:
    return "luck" in c.traits


def _add_bonus_die(rec: RollRecord, dice: Dice, notation: str, label: str, actor: str) -> int:
    bonus = dice.roll(notation, purpose=label, actor=actor)
    rec.modifier += bonus.total
    rec.total += bonus.total
    rec.notes.append(f"{label} +{bonus.total} ({bonus.id})")
    return bonus.total


def _settle(rec: RollRecord, dc: int | None) -> RollRecord:
    rec.dc = dc
    if dc is not None:
        rec.success = rec.total >= dc
    return rec


def ability_check(
    c: Creature,
    dice: Dice,
    ability: str | None = None,
    skill: str | None = None,
    dc: int | None = None,
    advantage: bool = False,
    disadvantage: bool = False,
    purpose: str | None = None,
    tool_proficient: bool = False,
    use_guidance: bool = True,
) -> RollRecord:
    """An ability check, optionally with a skill (e.g. ``skill="stealth"``)."""
    if skill:
        ability = ability or SKILLS[skill]
        # A skill can be rolled with a different ability (SRD); proficiency still applies.
        bonus = c.skill_bonus(skill) - c.mod(SKILLS[skill]) + c.mod(ability)
    else:
        if ability is None:
            raise ValueError("ability or skill is required")
        bonus = c.mod(ability) + (c.proficiency if tool_proficient else 0)
    bonus -= 2 * c.exhaustion
    if c.has_condition("poisoned") or c.has_condition("frightened"):
        disadvantage = True
    if skill == "stealth" and c.armor:
        from . import data

        if data.armor()[c.armor].get("stealth_disadvantage"):
            disadvantage = True
    label = purpose or f"{skill or ability} check"
    rec = c_d20(c, dice, bonus, advantage, disadvantage, label)
    guidance = c.effect("guidance")
    if use_guidance and guidance:
        _add_bonus_die(rec, dice, guidance.data.get("check_bonus", "1d4"), "guidance", c.id)
    return _settle(rec, dc)


def c_d20(c: Creature, dice: Dice, modifier: int, advantage: bool, disadvantage: bool, purpose: str,
          target: str | None = None) -> RollRecord:
    return dice.d20(
        modifier=modifier, advantage=advantage, disadvantage=disadvantage, purpose=purpose,
        actor=c.id, target=target, reroll_ones=_luck(c),
    )


def saving_throw(
    c: Creature,
    dice: Dice,
    ability: str,
    dc: int,
    advantage: bool = False,
    disadvantage: bool = False,
    purpose: str | None = None,
    against: set[str] | None = None,
    source: str | None = None,
) -> RollRecord:
    """A saving throw. ``against`` names what the save is against
    (e.g. {"poisoned"}, {"frightened"}, {"charmed"}, {"spell"}) so species
    traits can grant advantage."""
    against = against or set()
    label = purpose or f"{ability} save"
    if ability in ("str", "dex") and any(c.has_condition(x) for x in AUTO_FAIL_SAVE_CONDITIONS):
        rec = dice.d20(modifier=c.save_bonus(ability), purpose=label, actor=c.id, target=source)
        rec.notes.append("automatic failure (condition)")
        rec.dc = dc
        rec.success = False
        return rec
    if ability == "dex" and c.has_condition("restrained"):
        disadvantage = True
    if "dwarven_resilience" in c.traits and "poisoned" in against:
        advantage = True
    if "brave" in c.traits and "frightened" in against:
        advantage = True
    if "fey_ancestry" in c.traits and "charmed" in against:
        advantage = True
    bonus = c.save_bonus(ability) - 2 * c.exhaustion
    rec = c_d20(c, dice, bonus, advantage, disadvantage, label, target=source)
    bless = c.effect("bless")
    if bless:
        _add_bonus_die(rec, dice, bless.data.get("save_bonus", "1d4"), "bless", c.id)
    return _settle(rec, dc)


def death_save(c: Creature, dice: Dice) -> tuple[RollRecord, dict]:
    """Roll a Death Saving Throw for a creature at 0 HP (SRD 5.2)."""
    rec = dice.d20(modifier=0, purpose="death save", actor=c.id, reroll_ones=_luck(c))
    rec.dc = 10
    outcome = {"natural": rec.natural, "result": None}
    if rec.natural == 20:
        c.heal(1)
        rec.success = True
        outcome["result"] = "revived"
    elif rec.natural == 1:
        c.death_saves["failures"] += 2
        rec.success = False
        outcome["result"] = "two_failures"
    elif rec.total >= 10:
        c.death_saves["successes"] += 1
        rec.success = True
        outcome["result"] = "success"
    else:
        c.death_saves["failures"] += 1
        rec.success = False
        outcome["result"] = "failure"
    if c.death_saves["failures"] >= 3:
        c.hp = 0
        c.dead = True
        c.remove_condition("unconscious")
        outcome["result"] = "died"
    elif c.death_saves["successes"] >= 3:
        c.stable = True
        c.death_saves = {"successes": 0, "failures": 0}
        outcome["result"] = "stable"
    outcome["death_saves"] = dict(c.death_saves)
    return rec, outcome


def contest(a: Creature, a_skill: str, b: Creature, b_skill: str, dice: Dice,
            purpose: str = "contest") -> dict:
    """Contested check. Ties keep the status quo (``winner`` is None)."""
    ra = ability_check(a, dice, skill=a_skill, purpose=f"{purpose}: {a.id}")
    rb = ability_check(b, dice, skill=b_skill, purpose=f"{purpose}: {b.id}")
    winner = a.id if ra.total > rb.total else b.id if rb.total > ra.total else None
    return {"a": ra, "b": rb, "winner": winner}


def group_check(creatures: list[Creature], skill: str, dc: int, dice: Dice,
                purpose: str | None = None) -> dict:
    """Group check: succeeds if at least half the group succeeds."""
    rolls = [ability_check(c, dice, skill=skill, dc=dc, purpose=purpose or f"group {skill}") for c in creatures]
    passed = sum(1 for r in rolls if r.success)
    return {"rolls": rolls, "passed": passed, "success": passed * 2 >= len(creatures)}
