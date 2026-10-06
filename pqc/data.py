"""Loads the static game data in /data (equipment, spells, monsters, classes)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    with open(DATA_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def weapons() -> dict:
    return _load("equipment")["weapons"]


def armor() -> dict:
    return _load("equipment")["armor"]


def shield_bonus() -> int:
    return _load("equipment")["shield"]["ac_bonus"]


def items() -> dict:
    return _load("equipment")["items"]


def spells() -> dict:
    return _load("spells")["spells"]


def spell(spell_id: str) -> dict:
    try:
        return spells()[spell_id]
    except KeyError as exc:
        raise KeyError(f"Unknown spell id: {spell_id}") from exc


def monsters() -> dict:
    return _load("monsters")["monsters"]


def classes() -> dict:
    return _load("classes")["classes"]


def species() -> dict:
    return _load("classes")["species"]


def full_caster_slots(level: int) -> list[int]:
    return _load("classes")["full_caster_slots"][str(level)]


def xp_thresholds() -> list[int]:
    return _load("classes")["xp_thresholds"]


def column(table: dict, level: int, default=0):
    """Read a sparse level column such as {"1": 2, "4": 3} at ``level``."""
    value = default
    for lvl in sorted(table, key=int):
        if int(lvl) <= level:
            value = table[lvl]
    return value


def level_plans() -> dict:
    """Planned level-up choices per party member (from the dossiers)."""
    return {k: v for k, v in _load("level_plans").items() if not k.startswith("_")}
