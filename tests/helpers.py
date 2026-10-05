"""Test helpers: scripted dice and quick builders."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pqc.combat import Encounter  # noqa: E402
from pqc.creature import Attack, Creature  # noqa: E402
from pqc.dice import Dice, Draw  # noqa: E402
from pqc.state import GENESIS_PARTY_DIR as PARTY_DIR  # noqa: E402  (tests use the series-start sheets)
from pqc.state import character_from_sheet, load_json, load_party, monster_from_data  # noqa: E402


class ScriptedDice(Dice):
    """Dice whose die faces come from a list, in order. Raises when exhausted.

    The log, notation, advantage and success logic are the real ones; only the
    random source is replaced, so rule tests can control every face.
    """

    def __init__(self, faces: list[int], seed: str = "TEST"):
        super().__init__(seed)
        self.faces = list(faces)

    def _draw(self, sides: int) -> Draw:
        if not self.faces:
            raise AssertionError(f"ScriptedDice exhausted (needed a d{sides})")
        v = self.faces.pop(0)
        if not 1 <= v <= sides:
            raise AssertionError(f"Scripted face {v} impossible on a d{sides}")
        counter = self._counter
        self._counter += 1
        return Draw(counter, sides, v)


def pc(name: str) -> Creature:
    return character_from_sheet(load_json(PARTY_DIR / f"{name}.json"))


def party() -> dict[str, Creature]:
    return load_party(PARTY_DIR)


def mon(kind: str, cid: str | None = None, pos=(0, 0)) -> Creature:
    return monster_from_data(kind, cid or kind, pos=pos)


def scene(creatures: list[Creature], faces: list[int], order: list[str] | None = None) -> Encounter:
    """A started encounter with a fixed order (first in ``order`` acts first)."""
    enc = Encounter(creatures, ScriptedDice(faces))
    enc.start(order=order or [c.id for c in creatures])
    return enc


def dummy(cid="dummy", ac=10, hp=50, team="enemies", pos=(1, 0), **kw) -> Creature:
    return Creature(id=cid, name=cid, kind="monster", team=team, abilities={a: 10 for a in ("str", "dex", "con", "int", "wis", "cha")},
                    max_hp=hp, hp=hp, natural_ac=ac, pos=pos,
                    attacks=[Attack(id="club", name="Club", type="melee", to_hit=2, damage="1d4", damage_type="bludgeoning")], **kw)
