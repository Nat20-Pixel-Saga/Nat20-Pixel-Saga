"""Core 5e numbers: ability modifiers, proficiency, skills, sizes, distance."""
from __future__ import annotations

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")

SKILLS = {
    "acrobatics": "dex",
    "animal_handling": "wis",
    "arcana": "int",
    "athletics": "str",
    "deception": "cha",
    "history": "int",
    "insight": "wis",
    "intimidation": "cha",
    "investigation": "int",
    "medicine": "wis",
    "nature": "int",
    "perception": "wis",
    "performance": "cha",
    "persuasion": "cha",
    "religion": "int",
    "sleight_of_hand": "dex",
    "stealth": "dex",
    "survival": "wis",
}

# Flanking (optional rule, bible 10 §4) is used once the whole party is above level 2.
FLANKING_FROM_LEVEL = 3

SIZES = ("tiny", "small", "medium", "large", "huge", "gargantuan")

DAMAGE_TYPES = (
    "acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic",
    "piercing", "poison", "psychic", "radiant", "slashing", "thunder",
)

CONDITIONS = (
    "blinded", "charmed", "deafened", "frightened", "grappled", "incapacitated",
    "invisible", "paralyzed", "petrified", "poisoned", "prone", "restrained",
    "stunned", "unconscious",
)

# Conditions that also count as Incapacitated (SRD 5.2).
INCAPACITATING = {"incapacitated", "paralyzed", "petrified", "stunned", "unconscious"}

DC_LADDER = {"very_easy": 5, "easy": 10, "medium": 15, "hard": 20, "very_hard": 25, "nearly_impossible": 30}


def modifier(score: int) -> int:
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    if not 1 <= level <= 20:
        raise ValueError(f"Level out of range: {level}")
    return 2 + (level - 1) // 4


def size_index(size: str) -> int:
    return SIZES.index(size)


def distance_ft(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Grid distance with 5-ft squares; diagonals cost 5 ft (SRD default)."""
    return 5 * max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def cr_to_float(cr: str | float | int) -> float:
    if isinstance(cr, (int, float)):
        return float(cr)
    if "/" in cr:
        n, d = cr.split("/")
        return int(n) / int(d)
    return float(cr)
