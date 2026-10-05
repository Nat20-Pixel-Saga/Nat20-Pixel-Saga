"""Seeded, auditable dice.

Every die is derived from HMAC-SHA256(seed, draw_counter) with rejection
sampling, so the sequence is deterministic for a seed and any single die can be
re-verified from the seed and the counter recorded in the log.

Usage::

    dice = Dice("C01-E001-1")
    rec = dice.d20(modifier=5, purpose="attack", actor="brannoc", target="goblin-1", dc=15)
    rec.total, rec.natural, rec.success
    dice.roll("2d6+3", purpose="damage")
    Dice.verify_log("C01-E001-1", [r.to_dict() for r in dice.log])  # -> True
"""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from typing import Iterable

_NOTATION = re.compile(
    r"^\s*(?P<count>\d*)\s*d\s*(?P<sides>\d+)\s*(?:(?P<keep>k[hl])(?P<keepn>\d+))?\s*(?P<mod>[+-]\s*\d+)?\s*$",
    re.IGNORECASE,
)
_FLAT = re.compile(r"^\s*(?P<mod>[+-]?\s*\d+)\s*$")

VALID_SIDES = {2, 3, 4, 6, 8, 10, 12, 20, 100}


class DiceError(ValueError):
    pass


@dataclass(frozen=True)
class DiceSpec:
    count: int
    sides: int
    keep: str | None = None  # "kh" or "kl"
    keep_n: int | None = None
    modifier: int = 0

    @classmethod
    def parse(cls, notation: str) -> "DiceSpec":
        flat = _FLAT.match(notation)
        if flat:
            return cls(count=0, sides=0, modifier=int(flat.group("mod").replace(" ", "")))
        m = _NOTATION.match(notation)
        if not m:
            raise DiceError(f"Unparseable dice notation: {notation!r}")
        count = int(m.group("count") or 1)
        sides = int(m.group("sides"))
        if sides not in VALID_SIDES:
            raise DiceError(f"Unsupported die d{sides}")
        if count < 1 or count > 200:
            raise DiceError(f"Dice count out of range: {count}")
        keep = m.group("keep").lower() if m.group("keep") else None
        keep_n = int(m.group("keepn")) if m.group("keepn") else None
        if keep and not (1 <= keep_n <= count):
            raise DiceError(f"Keep count out of range in {notation!r}")
        mod = int(m.group("mod").replace(" ", "")) if m.group("mod") else 0
        return cls(count, sides, keep, keep_n, mod)

    def scaled(self, factor: int) -> "DiceSpec":
        """Multiply the number of dice (critical hits, cantrip scaling)."""
        return DiceSpec(self.count * factor, self.sides, self.keep, self.keep_n, self.modifier)

    def plus_dice(self, extra: int) -> "DiceSpec":
        return DiceSpec(self.count + extra, self.sides, self.keep, self.keep_n, self.modifier)

    def __str__(self) -> str:
        if self.count == 0:
            return str(self.modifier)
        s = f"{self.count}d{self.sides}"
        if self.keep:
            s += f"{self.keep}{self.keep_n}"
        if self.modifier:
            s += f"{self.modifier:+d}"
        return s

    @property
    def average(self) -> float:
        if self.count == 0:
            return float(self.modifier)
        return self.count * (self.sides + 1) / 2 + self.modifier


@dataclass
class Draw:
    counter: int
    sides: int
    value: int

    def to_dict(self) -> dict:
        return {"counter": self.counter, "sides": self.sides, "value": self.value}


@dataclass
class RollRecord:
    """One logged roll. ``kind`` is "d20" for d20 tests and "dice" otherwise."""

    id: str
    index: int
    seed: str
    kind: str
    notation: str
    purpose: str
    actor: str | None
    target: str | None
    draws: list[Draw]
    kept: list[int]
    modifier: int
    total: int
    advantage: str = "none"  # none | advantage | disadvantage
    natural: int | None = None
    dc: int | None = None
    success: bool | None = None
    critical: bool = False
    fumble: bool = False
    rerolled: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def rolls(self) -> list[int]:
        return [d.value for d in self.draws]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "index": self.index,
            "seed": self.seed,
            "kind": self.kind,
            "notation": self.notation,
            "purpose": self.purpose,
            "actor": self.actor,
            "target": self.target,
            "draws": [d.to_dict() for d in self.draws],
            "rolls": self.rolls,
            "kept": self.kept,
            "modifier": self.modifier,
            "total": self.total,
            "advantage": self.advantage,
            "natural": self.natural,
            "dc": self.dc,
            "success": self.success,
            "critical": self.critical,
            "fumble": self.fumble,
            "rerolled": self.rerolled,
            "notes": self.notes,
        }

    def overlay_text(self) -> str:
        """The line shown in the on-screen dice tray."""
        if self.kind == "d20":
            mod = f" {'+' if self.modifier >= 0 else '-'} {abs(self.modifier)}" if self.modifier else ""
            if self.advantage != "none":
                arrow = "ADV" if self.advantage == "advantage" else "DIS"
                faces = "|".join(str(v) for v in self.rolls[:2])
                base = f"d20 {arrow} ({faces} → {self.natural}){mod} = {self.total}"
            else:
                base = f"d20 ({self.natural}){mod} = {self.total}"
            if self.dc is not None:
                verdict = "SUCCESS" if self.success else "FAIL"
                base += f" vs {self.dc} — {verdict}"
            if self.critical:
                base += " — CRITICAL!"
            return base
        mod = f" {'+' if self.modifier >= 0 else '-'} {abs(self.modifier)}" if self.modifier else ""
        return f"{self.notation}: [{', '.join(map(str, self.kept))}]{mod} = {self.total}"


def _die_from_counter(seed: str, counter: int, sides: int) -> int | None:
    """Return a die value for this counter, or None if this draw is rejected."""
    digest = hmac.new(seed.encode("utf-8"), str(counter).encode("ascii"), hashlib.sha256).digest()
    value = int.from_bytes(digest[:8], "big")
    limit = (2**64 // sides) * sides
    if value >= limit:
        return None
    return value % sides + 1


class Dice:
    """Deterministic dice for one seed. Keeps a full log of every roll."""

    def __init__(self, seed: str):
        if not seed:
            raise DiceError("A non-empty seed is required")
        self.seed = str(seed)
        self._counter = 0
        self.log: list[RollRecord] = []

    # ----------------------------------------------------------------- core
    def _draw(self, sides: int) -> Draw:
        while True:
            counter = self._counter
            self._counter += 1
            value = _die_from_counter(self.seed, counter, sides)
            if value is not None:
                return Draw(counter, sides, value)

    def _record(self, **kw) -> RollRecord:
        index = len(self.log)
        rec = RollRecord(id=f"r{index:04d}", index=index, seed=self.seed, **kw)
        self.log.append(rec)
        return rec

    @property
    def draw_counter(self) -> int:
        return self._counter

    # ---------------------------------------------------------------- rolls
    def roll(
        self,
        notation: str | DiceSpec,
        purpose: str = "",
        actor: str | None = None,
        target: str | None = None,
        extra_modifier: int = 0,
        notes: Iterable[str] = (),
    ) -> RollRecord:
        """Roll a dice expression such as ``2d6+3`` or ``4d6kh3``."""
        spec = notation if isinstance(notation, DiceSpec) else DiceSpec.parse(notation)
        draws = [self._draw(spec.sides) for _ in range(spec.count)]
        values = [d.value for d in draws]
        if spec.keep == "kh":
            kept = sorted(values, reverse=True)[: spec.keep_n]
        elif spec.keep == "kl":
            kept = sorted(values)[: spec.keep_n]
        else:
            kept = list(values)
        modifier = spec.modifier + extra_modifier
        return self._record(
            kind="dice",
            notation=str(spec),
            purpose=purpose,
            actor=actor,
            target=target,
            draws=draws,
            kept=kept,
            modifier=modifier,
            total=sum(kept) + modifier,
            notes=list(notes),
        )

    def d20(
        self,
        modifier: int = 0,
        advantage: bool = False,
        disadvantage: bool = False,
        purpose: str = "",
        actor: str | None = None,
        target: str | None = None,
        dc: int | None = None,
        reroll_ones: bool = False,
        crit_range: int = 20,
        is_attack: bool = False,
        notes: Iterable[str] = (),
    ) -> RollRecord:
        """A D20 Test. Advantage and disadvantage cancel out.

        ``reroll_ones`` implements Halfling Luck: one natural 1 is rerolled and
        the new value must be used. ``is_attack`` enables natural-20 critical
        hits (with ``crit_range``) and natural-1 automatic misses; for checks
        and saves natural 1 and 20 have no special effect (SRD 5.2).
        """
        mode = "none"
        if advantage and not disadvantage:
            mode = "advantage"
        elif disadvantage and not advantage:
            mode = "disadvantage"
        n = 2 if mode != "none" else 1
        draws = [self._draw(20) for _ in range(n)]
        rerolled: list[int] = []
        values = [d.value for d in draws]
        if reroll_ones and 1 in values:
            i = values.index(1)
            new = self._draw(20)
            rerolled.append(values[i])
            draws.append(new)
            values[i] = new.value
        if mode == "advantage":
            natural = max(values)
        elif mode == "disadvantage":
            natural = min(values)
        else:
            natural = values[0]
        total = natural + modifier
        critical = is_attack and natural >= crit_range
        fumble = is_attack and natural == 1
        success = None
        if dc is not None:
            if is_attack:
                success = (not fumble) and (critical or total >= dc)
            else:
                success = total >= dc
        return self._record(
            kind="d20",
            notation="1d20" if n == 1 else ("2d20kh1" if mode == "advantage" else "2d20kl1"),
            purpose=purpose,
            actor=actor,
            target=target,
            draws=draws,
            kept=[natural],
            modifier=modifier,
            total=total,
            advantage=mode,
            natural=natural,
            dc=dc,
            success=success,
            critical=critical,
            fumble=fumble,
            rerolled=rerolled,
            notes=list(notes),
        )

    # ----------------------------------------------------------- auditing
    @staticmethod
    def verify_record(record: dict) -> bool:
        """Recompute every draw of a logged roll from its seed and counters."""
        seed = record["seed"]
        for draw in record["draws"]:
            if _die_from_counter(seed, draw["counter"], draw["sides"]) != draw["value"]:
                return False
        return True

    @staticmethod
    def verify_log(seed: str, records: list[dict]) -> bool:
        """Verify a whole log: values, seed and strictly increasing counters."""
        last = -1
        for rec in records:
            if rec["seed"] != seed or not Dice.verify_record(rec):
                return False
            for draw in rec["draws"]:
                if draw["counter"] <= last:
                    return False
                last = draw["counter"]
        return True

    def export_log(self) -> list[dict]:
        return [r.to_dict() for r in self.log]
