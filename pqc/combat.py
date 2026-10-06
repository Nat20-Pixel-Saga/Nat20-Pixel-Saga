"""Turn-based 5e combat (SRD 5.2) driven by JSON intents.

The planner or an LLM never rolls dice: it submits *intents* (``{"type":
"attack", "attack": "longsword", "target": "goblin-1"}``); the encounter checks
they are legal, rolls every die through :class:`pqc.dice.Dice`, applies the
rules and appends machine-readable events. ``legal_actions()`` lists every
intent the current creature may take, which is what the tactical model is
shown.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import data
from .checks import ability_check, death_save, saving_throw
from .creature import Attack, Creature, Effect
from .dice import Dice, DiceSpec, RollRecord
from . import grid
from .rules import distance_ft, size_index


class EngineError(ValueError):
    """An intent that is not legal right now. Nothing is changed or rolled."""


@dataclass
class TurnState:
    actions: int = 1
    bonus_action: bool = True
    movement: int = 0
    attacks_left: int = 0
    disengaged: bool = False
    sneak_attack_used: bool = False
    savage_attacker_used: bool = False
    slot_spell_cast: bool = False
    bonus_slot_spell_cast: bool = False
    action_surge_used: bool = False
    resistance_cantrip_used: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


Policy = Callable[["Encounter", Creature], "dict | list[dict] | None"]


def hit_chance(to_hit: int, ac: int, advantage: bool = False, disadvantage: bool = False) -> float:
    p = min(0.95, max(0.05, (21 - (ac - to_hit)) / 20))
    if advantage and not disadvantage:
        return 1 - (1 - p) ** 2
    if disadvantage and not advantage:
        return p * p
    return p


class Encounter:
    def __init__(self, combatants: list[Creature], dice: Dice, name: str = "encounter",
                 auto_reactions: bool = True, occupied_extra: set[tuple[int, int]] | None = None,
                 difficult: set[tuple[int, int]] | None = None, options: dict | None = None):
        """``occupied_extra``: impassable squares (walls, trees, houses).
        ``difficult``: difficult-terrain squares (double movement cost).
        ``options``: optional rules, e.g. {"flanking": True} (off by default, bible 10 §4)."""
        ids = [c.id for c in combatants]
        if len(ids) != len(set(ids)):
            raise EngineError("Combatant ids must be unique")
        self.name = name
        self.dice = dice
        self.creatures: dict[str, Creature] = {c.id: c for c in combatants}
        self.order: list[str] = []
        self.initiative: dict[str, int] = {}
        self.round = 0
        self.turn_index = -1
        self.turn = TurnState()
        self.reactions: dict[str, bool] = {c.id: True for c in combatants}
        self.events: list[dict] = []
        self.auto_reactions = auto_reactions
        self.blocked = set(occupied_extra or ())
        self.difficult = set(difficult or ())
        self.options = {"flanking": False, "tactics": 1, **(options or {})}
        self._once: dict[tuple[str, str], tuple[int, int]] = {}   # (feature, creature) -> turn it was used
        self.ai_memo: dict[str, dict] = {}      # what the tactical policy remembers per creature, this fight
        self.started = False
        self.finished = False

    # ================================================================ util
    def emit(self, t: str, **kw) -> dict:
        ev = {"seq": len(self.events), "round": self.round, "t": t, **kw}
        self.events.append(ev)
        return ev

    def get(self, cid: str) -> Creature:
        try:
            return self.creatures[cid]
        except KeyError as exc:
            raise EngineError(f"Unknown creature {cid!r}") from exc

    @property
    def current(self) -> Creature:
        return self.creatures[self.order[self.turn_index]]

    def enemies_of(self, c: Creature, standing_only: bool = True) -> list[Creature]:
        return [x for x in self.creatures.values() if x.team != c.team and (x.standing or not standing_only)]

    def allies_of(self, c: Creature, include_self: bool = False, standing_only: bool = True) -> list[Creature]:
        return [x for x in self.creatures.values() if x.team == c.team and (include_self or x.id != c.id)
                and (x.standing or not standing_only)]

    def dist(self, a: Creature, b: Creature) -> int:
        return distance_ft(a.pos, b.pos)

    def _once_per_turn(self, feature: str, c: Creature) -> bool:
        """Tactics 2: features usable "once per turn" (Sneak Attack, Savage Attacker) also work on a
        reaction during someone else's turn (SRD 5.2), once in each turn."""
        return self._once.get((feature, c.id)) != (self.round, self.turn_index)

    def _use_once(self, feature: str, c: Creature) -> None:
        self._once[(feature, c.id)] = (self.round, self.turn_index)

    def occupied(self, exclude: str | None = None) -> set[tuple[int, int]]:
        occ = {c.pos for c in self.creatures.values() if not c.dead and c.id != exclude}
        return occ | self.blocked

    def passable(self, c: Creature, sq: tuple[int, int]) -> bool:
        """Can ``c`` move through ``sq``? Walls block; hostile creatures block
        (unless two sizes apart, SRD); allies and the fallen don't."""
        if sq in self.blocked:
            return False
        for o in self.creatures.values():
            if o.id == c.id or o.dead or o.pos != sq:
                continue
            if o.team != c.team and o.standing and abs(size_index(o.size) - size_index(c.size)) < 2:
                return False
        return True

    def endable(self, c: Creature, sq: tuple[int, int]) -> bool:
        """Can ``c`` end its move in ``sq``? Not on a wall or another creature."""
        if sq in self.blocked:
            return False
        return not any(o.id != c.id and not o.dead and o.pos == sq for o in self.creatures.values())

    def step_cost(self, c: Creature, sq: tuple[int, int]) -> int:
        cost = 5
        if sq in self.difficult:
            cost += 5
        if c.has_condition("prone"):
            cost += 5
        return cost

    def reach_map(self, c: Creature, budget: int | None = None) -> dict:
        budget = self.turn.movement if budget is None else budget
        return grid.reachable(c.pos, budget, lambda sq: self.passable(c, sq), lambda sq: self.step_cost(c, sq))

    def provokers(self, c: Creature, path: list[tuple[int, int]]) -> list[str]:
        """Enemies that would get an opportunity attack along ``path``."""
        if self.turn.disengaged:
            return []
        out = []
        for e in self.enemies_of(c):
            if not self.reactions.get(e.id) or e.incapacitated or e.effect("no_opportunity_attacks"):
                continue
            reach = max((a.reach_ft for a in e.attacks if a.type == "melee"), default=0)
            if not reach:
                continue
            for a, b in zip(path, path[1:]):
                if distance_ft(a, e.pos) <= reach < distance_ft(b, e.pos):
                    out.append(e.id)
                    break
        return out

    # ======================================================== initiative
    def roll_initiative(self) -> None:
        scores = {}
        surprised = set(self.options.get("surprised") or ())
        for c in self.creatures.values():
            if c.id in surprised:    # SRD 5.2 Surprise: disadvantage on the Initiative roll
                rec = self.dice.d20(modifier=c.initiative_bonus, purpose="initiative (surprised)", actor=c.id,
                                    reroll_ones="luck" in c.traits, disadvantage=True)
            else:
                rec = self.dice.d20(modifier=c.initiative_bonus, purpose="initiative", actor=c.id,
                                    reroll_ones="luck" in c.traits)
            scores[c.id] = (rec.total, c.abilities["dex"])
            self.initiative[c.id] = rec.total
            self.emit("initiative", actor=c.id, roll=rec.id, total=rec.total)
        # Ties: higher Dex, then a seeded roll-off.
        tiebreak = {}
        groups: dict[tuple, list[str]] = {}
        for cid, key in scores.items():
            groups.setdefault(key, []).append(cid)
        for key, members in groups.items():
            if len(members) > 1:
                for cid in members:
                    tiebreak[cid] = self.dice.d20(purpose="initiative tiebreak", actor=cid).total
        self.order = sorted(scores, key=lambda cid: (scores[cid][0], scores[cid][1], tiebreak.get(cid, 0)),
                            reverse=True)
        self.emit("initiative_order", order=list(self.order))

    def start(self, order: list[str] | None = None) -> list[dict]:
        """Start the fight. ``order`` fixes the turn order without rolling
        (for planned surprise rounds and scripted tests)."""
        if self.started:
            raise EngineError("Encounter already started")
        self.started = True
        mark = len(self.events)
        self.emit("encounter_start", name=self.name, combatants=[c.summary() for c in self.creatures.values()])
        if order is not None:
            if sorted(order) != sorted(self.creatures):
                raise EngineError("Fixed order must list every combatant exactly once")
            self.order = list(order)
            self.emit("initiative_order", order=list(self.order), set_by_plan=True)
        else:
            self.roll_initiative()
        self.round = 1
        self.turn_index = 0
        self._start_turn()
        return self.events[mark:]

    # ============================================================== turns
    def _expire(self, when: str, cid: str) -> None:
        for c in self.creatures.values():
            keep = []
            for e in c.effects:
                if e.expires and e.expires[0] == when and e.expires[1] == cid:
                    if e.expires[2] > 0:
                        e.expires = (e.expires[0], e.expires[1], e.expires[2] - 1)
                        keep.append(e)
                    else:
                        self.emit("effect_end", target=c.id, effect=e.name, reason=f"{when} of {cid}'s turn")
                        continue
                else:
                    keep.append(e)
            c.effects = keep

    def _tick_durations(self, source_id: str) -> None:
        """At the end of the source's turn, count down effects it created."""
        ended_conc = False
        for c in self.creatures.values():
            keep = []
            for e in c.effects:
                if e.source == source_id and e.rounds_left is not None:
                    e.rounds_left -= 1
                    if e.rounds_left <= 0:
                        self.emit("effect_end", target=c.id, effect=e.name, reason="duration")
                        ended_conc = ended_conc or e.concentration
                        continue
                keep.append(e)
            c.effects = keep
        src = self.creatures.get(source_id)
        if ended_conc and src and src.concentration:
            still = any(e.concentration and e.source == source_id for x in self.creatures.values() for e in x.effects)
            if not still:
                src.concentration = None

    def _start_turn(self) -> None:
        c = self.current
        self._expire("start", c.id)
        self.reactions[c.id] = True
        self.turn = TurnState(movement=c.current_speed)
        self.emit("turn_start", actor=c.id, hp=c.hp, pos=list(c.pos))
        if c.dead:
            return
        if c.hp == 0 and c.kind == "pc" and not c.stable:
            rec, outcome = death_save(c, self.dice)
            self.emit("death_save", actor=c.id, roll=rec.id, **outcome)
            if c.dead:
                self.emit("death", actor=c.id, cause="death saves")

    def end_turn(self) -> list[dict]:
        mark = len(self.events)
        c = self.current
        self._expire("end", c.id)
        self._tick_durations(c.id)
        self.emit("turn_end", actor=c.id)
        if self.is_over():
            self._finish()
            return self.events[mark:]
        n = len(self.order)
        for _ in range(n):
            self.turn_index += 1
            if self.turn_index >= n:
                self.turn_index = 0
                self.round += 1
                self.emit("round_start")
            if not self.current.dead:
                break
        self._start_turn()
        return self.events[mark:]

    def can_act(self, c: Creature) -> bool:
        return c.standing and not c.incapacitated

    def is_over(self) -> str | None:
        teams = {c.team for c in self.creatures.values()}
        standing = {t for t in teams if any(c.standing and c.team == t for c in self.creatures.values())}
        if len(standing) <= 1:
            return next(iter(standing), "none")
        return None

    def _finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        winner = self.is_over()
        xp = sum(c.xp_value for c in self.creatures.values() if c.team != winner and c.kind == "monster" and not c.standing)
        self.emit("encounter_end", winner=winner, rounds=self.round, xp=xp,
                  survivors=[c.summary() for c in self.creatures.values()])

    # ========================================================== effects
    def end_concentration(self, c: Creature, reason: str) -> None:
        if not c.concentration:
            return
        spell = c.concentration
        c.concentration = None
        for x in self.creatures.values():
            gone = x.remove_effects(lambda e: e.concentration and e.source == c.id)
            for e in gone:
                self.emit("effect_end", target=x.id, effect=e.name, reason="concentration ended")
        self.emit("concentration_end", actor=c.id, spell=spell, reason=reason)

    def _concentration_check(self, c: Creature, damage: int) -> None:
        if not c.concentration or damage <= 0:
            return
        if not c.standing or c.incapacitated:
            self.end_concentration(c, "incapacitated")
            return
        dc = min(30, max(10, damage // 2))
        rec = saving_throw(c, self.dice, "con", dc, purpose="concentration")
        self.emit("concentration_check", actor=c.id, roll=rec.id, dc=dc, success=rec.success)
        if not rec.success:
            self.end_concentration(c, "failed concentration save")

    # ============================================================ damage
    def _roll_damage(self, notation: str, critical: bool, purpose: str, actor: str, target: str,
                     savage: bool = False) -> tuple[int, list[str]]:
        spec = DiceSpec.parse(notation)
        if critical and spec.count:
            spec = spec.scaled(2)
        rec = self.dice.roll(spec, purpose=purpose, actor=actor, target=target)
        ids = [rec.id]
        total = rec.total
        if savage and spec.count:
            rec2 = self.dice.roll(spec, purpose=purpose + " (Savage Attacker)", actor=actor, target=target)
            ids.append(rec2.id)
            if rec2.total > total:
                total = rec2.total
                rec2.notes.append("kept (Savage Attacker)")
            else:
                rec.notes.append("kept (Savage Attacker)")
        return max(0, total), ids

    def apply_damage(self, target: Creature, parts: dict[str, int], critical: bool = False,
                     source: str | None = None) -> dict:
        """Apply typed damage parts to a creature, with all the follow-ups."""
        total_taken = 0
        results = []
        for dtype, amount in parts.items():
            amount, note = target.adjust_damage(amount, dtype)
            res_cantrip = target.effect("resistance_cantrip")
            if res_cantrip and amount > 0 and res_cantrip.data.get("damage_type") == dtype \
                    and not res_cantrip.data.get("used_round") == (self.round, self.order[self.turn_index] if self.order else None):
                red = self.dice.roll(res_cantrip.data.get("reduce", "1d4"), purpose="Resistance cantrip", actor=target.id)
                amount = max(0, amount - red.total)
                res_cantrip.data["used_round"] = (self.round, self.order[self.turn_index] if self.order else None)
                note = (note + "+resistance cantrip") if note else "resistance cantrip"
            # Undead Fortitude (zombies).
            if "undead_fortitude" in target.traits and target.hp > 0 and amount >= target.hp + target.temp_hp \
                    and dtype != "radiant" and not critical:
                rec = saving_throw(target, self.dice, "con", 5 + amount, purpose="Undead Fortitude")
                self.emit("trait", actor=target.id, trait="undead_fortitude", roll=rec.id, success=rec.success)
                if rec.success:
                    target.temp_hp = 0
                    before = target.hp
                    target.hp = 1
                    results.append({"amount": before - 1, "type": dtype, "note": "undead fortitude",
                                    "hp_before": before, "hp_after": 1})
                    total_taken += before - 1
                    continue
            res = target.take_damage(amount, dtype, critical=critical, already_adjusted=True)
            if note:
                res["note"] = note
            results.append(res)
            total_taken += res["amount"]
            if res["died"]:
                self.emit("death", actor=target.id, cause=source or "damage", instant=res["instant_death"])
            elif res["dropped_to_zero"]:
                self.emit("down", actor=target.id)
        if total_taken and target.effect("sanctuary") and source:
            pass  # Taking damage doesn't end Sanctuary; dealing it does.
        if target.concentration:
            if not target.standing:
                self.end_concentration(target, "dropped to 0 HP")
            else:
                self._concentration_check(target, total_taken)
        return {"target": target.id, "total": total_taken, "parts": results, "hp_after": target.hp}

    # =================================================== attack resolution
    def _attack_modifiers(self, attacker: Creature, target: Creature, ranged: bool,
                          long_range: bool) -> tuple[bool, bool, list[str]]:
        adv, dis, why = False, False, []

        def a(reason):
            nonlocal adv
            adv = True
            why.append(f"+{reason}")

        def d(reason):
            nonlocal dis
            dis = True
            why.append(f"-{reason}")

        for cond in ("blinded", "poisoned", "frightened", "prone", "restrained"):
            if attacker.has_condition(cond):
                d(f"attacker {cond}")
        if attacker.has_condition("invisible") or attacker.effect("hidden"):
            a("attacker unseen")
        for cond in ("blinded", "restrained", "paralyzed", "stunned", "petrified", "unconscious"):
            if target.has_condition(cond):
                a(f"target {cond}")
        if target.has_condition("invisible") or target.effect("hidden"):
            d("target unseen")
        within5 = self.dist(attacker, target) <= 5
        if target.has_condition("prone"):
            if within5:
                a("target prone")
            else:
                d("target prone at range")
        if target.effect("dodge") and not target.incapacitated:
            d("target dodging")
        if ranged:
            if long_range:
                d("long range")
            if any(self.dist(attacker, e) <= 5 and not e.incapacitated for e in self.enemies_of(attacker)):
                d("hostile within 5 ft")
        if self.options.get("flanking") and not ranged and within5:
            ox, oy = 2 * target.pos[0] - attacker.pos[0], 2 * target.pos[1] - attacker.pos[1]
            if any(al.pos == (ox, oy) and not al.incapacitated for al in self.allies_of(attacker)):
                a("flanking")
        if "pack_tactics" in attacker.traits and any(
                self.dist(ally, target) <= 5 and not ally.incapacitated for ally in self.allies_of(attacker)):
            a("pack tactics")
        for e in attacker.effects_named("vex"):
            if e.data.get("target") == target.id:
                a("vex")
        if attacker.effect("sapped"):
            d("sapped")
        if target.effect("guiding_bolt"):
            a("guiding bolt")
        for e in target.effects_named("help_target"):
            helper = self.creatures.get(e.data.get("by"))
            if helper and helper.team == attacker.team and helper.id != attacker.id:
                a("help")
        return adv, dis, why

    def _consume_attack_markers(self, attacker: Creature, target: Creature) -> None:
        attacker.remove_effects(lambda e: e.name == "vex" and e.data.get("target") == target.id)
        attacker.remove_effects(lambda e: e.name == "sapped")
        attacker.remove_effects(lambda e: e.name == "hidden")
        target.remove_effects(lambda e: e.name == "guiding_bolt")
        target.remove_effects(lambda e: e.name == "help_target" and self.creatures.get(e.data.get("by"))
                              and self.creatures[e.data["by"]].team == attacker.team)
        if attacker.effect("sanctuary"):
            attacker.remove_effects(lambda e: e.name == "sanctuary")
            self.emit("effect_end", target=attacker.id, effect="sanctuary", reason="warded creature attacked")

    def _sanctuary_blocks(self, attacker: Creature, target: Creature) -> bool:
        sanc = target.effect("sanctuary")
        if not sanc or attacker.team == target.team:
            return False
        rec = saving_throw(attacker, self.dice, "wis", sanc.data["dc"], purpose="Sanctuary", source=target.id)
        self.emit("sanctuary", actor=attacker.id, target=target.id, roll=rec.id, success=rec.success)
        return not rec.success

    def _try_shield(self, target: Creature, attack_total: int, natural: int, crit_range: int) -> bool:
        """Auto-cast Shield if it turns this hit into a miss. Returns True if cast."""
        if not self.auto_reactions or not self.reactions.get(target.id) or not target.conscious:
            return False
        if not target.knows_spell("shield") or natural >= crit_range:
            return False
        if not (target.ac <= attack_total < target.ac + 5):
            return False
        slot = target.lowest_slot_at_least(1)
        if slot is None:
            return False
        self._spend_slot(target, slot)
        self.reactions[target.id] = False
        target.add_effect(Effect("shield_spell", target.id, {"ac_bonus": 5}, expires=("start", target.id, 0)))
        self.emit("reaction", actor=target.id, reaction="shield", slot=slot, ac=target.ac)
        return True

    def _attack_roll(self, attacker: Creature, target: Creature, to_hit: int, ranged: bool, long_range: bool,
                     label: str, crit_range: int = 20) -> tuple[RollRecord, bool, bool, list[str]]:
        adv, dis, why = self._attack_modifiers(attacker, target, ranged, long_range)
        to_hit -= 2 * attacker.exhaustion
        rec = self.dice.d20(modifier=to_hit, advantage=adv, disadvantage=dis, purpose=label, actor=attacker.id,
                            target=target.id, dc=target.ac, reroll_ones="luck" in attacker.traits,
                            crit_range=crit_range, is_attack=True, notes=why)
        bless = attacker.effect("bless")
        if bless:
            b = self.dice.roll(bless.data.get("attack_bonus", "1d4"), purpose="bless", actor=attacker.id)
            rec.modifier += b.total
            rec.total += b.total
            rec.notes.append(f"bless +{b.total} ({b.id})")
            rec.success = (not rec.fumble) and (rec.critical or rec.total >= rec.dc)
        hit = bool(rec.success)
        if hit and self._try_shield(target, rec.total, rec.natural, crit_range):
            rec.dc = target.ac
            hit = rec.critical or rec.total >= target.ac
            rec.success = hit
            rec.notes.append("target cast Shield")
        crit = hit and rec.critical
        if hit and not crit and self.dist(attacker, target) <= 5 and not ranged and \
                (target.has_condition("paralyzed") or target.has_condition("unconscious")):
            crit = True
            rec.critical = True
            rec.notes.append("automatic critical (helpless target within 5 ft)")
        had_adv = rec.advantage == "advantage"
        self._consume_attack_markers(attacker, target)
        return rec, hit, crit, why + (["had_advantage"] if had_adv else [])

    def _check_target(self, attacker: Creature, target: Creature) -> None:
        if target.dead:
            raise EngineError(f"{target.id} is dead")
        if target.id == attacker.id:
            raise EngineError("A creature cannot target itself with an attack")

    def _range_check(self, attacker: Creature, target: Creature, atk: Attack) -> bool:
        """Raise if out of range; return True if the attack is at long range."""
        d = self.dist(attacker, target)
        if atk.type == "melee":
            if d > atk.reach_ft:
                raise EngineError(f"{target.id} is {d} ft away; {atk.name} reach is {atk.reach_ft} ft")
            return False
        normal, long = atk.range or (5, 5)
        if d > long:
            raise EngineError(f"{target.id} is {d} ft away; {atk.name} range is {normal}/{long} ft")
        return d > normal

    def _ammo_key(self, c: Creature, atk: Attack) -> str | None:
        if c.kind != "pc" or not atk.weapon_id:
            return None
        if atk.thrown_mode:
            return atk.weapon_id
        if "ammunition" in atk.properties:
            return "bolts" if atk.weapon_id == "light_crossbow" else "arrows"
        return None

    def resolve_weapon_attack(self, attacker: Creature, target: Creature, atk: Attack,
                              opportunity: bool = False) -> dict:
        self._check_target(attacker, target)
        long_range = self._range_check(attacker, target, atk)
        ammo = self._ammo_key(attacker, atk)
        if ammo is not None:
            if attacker.inventory.get(ammo, 0) <= 0:
                raise EngineError(f"{attacker.id} has no {ammo} left")
            attacker.inventory[ammo] -= 1
            if atk.thrown_mode and attacker.inventory[ammo] == 0:
                # Thrown the last one: the melee mode needs it in hand.
                pass
        label = f"attack: {atk.name}" + (" (opportunity)" if opportunity else "")
        if self._sanctuary_blocks(attacker, target):
            self._consume_attack_markers(attacker, target)
            return self.emit("attack", actor=attacker.id, target=target.id, attack=atk.id, blocked="sanctuary",
                             hit=False)
        rec, hit, crit, why = self._attack_roll(attacker, target, atk.to_hit, atk.type == "ranged", long_range,
                                                label, attacker.crit_range)
        ev = self.emit("attack", actor=attacker.id, target=target.id, attack=atk.id, roll=rec.id, hit=hit,
                       critical=crit, total=rec.total, ac=rec.dc, advantage=rec.advantage,
                       overlay=rec.overlay_text(), opportunity=opportunity, damage_rolls=[])
        mastery = atk.mastery if atk.weapon_id and atk.weapon_id in attacker.weapon_masteries else None
        if not hit:
            if mastery == "graze":
                mod = attacker.mod(atk.ability or "str")
                if mod > 0:
                    ev["graze"] = self.apply_damage(target, {atk.damage_type: mod}, source=attacker.id)
            return ev

        parts: dict[str, int] = {}
        v2 = self.options.get("tactics", 1) >= 2
        if v2:
            savage = "savage_attacker" in attacker.feats and atk.is_weapon and self._once_per_turn("savage", attacker)
            if savage:
                self._use_once("savage", attacker)
        else:
            savage = "savage_attacker" in attacker.feats and atk.is_weapon and not self.turn.savage_attacker_used \
                and attacker.id == self.current.id
            if savage:
                self.turn.savage_attacker_used = True
        amount, ids = self._roll_damage(atk.damage, crit, f"damage: {atk.name}", attacker.id, target.id, savage)
        parts[atk.damage_type] = parts.get(atk.damage_type, 0) + amount
        ev["damage_rolls"] += ids
        for dice_s, dtype in atk.extra_damage:
            amt, ids = self._roll_damage(dice_s, crit, f"damage: {atk.name} ({dtype})", attacker.id, target.id)
            parts[dtype] = parts.get(dtype, 0) + amt
            ev["damage_rolls"] += ids
        if atk.extra_damage_if_advantage and "had_advantage" in why:
            amt, ids = self._roll_damage(atk.extra_damage_if_advantage, crit, f"damage: {atk.name} (advantage)",
                                         attacker.id, target.id)
            parts[atk.damage_type] += amt
            ev["damage_rolls"] += ids
        # Sneak Attack.
        sneak_free = self._once_per_turn("sneak", attacker) if v2 else (
            not self.turn.sneak_attack_used and attacker.id == self.current.id)
        if attacker.sneak_attack_dice and sneak_free and atk.finesse_or_ranged and rec.advantage != "disadvantage":
            ally_adjacent = any(self.dist(al, target) <= 5 and not al.incapacitated for al in self.allies_of(attacker))
            if rec.advantage == "advantage" or ally_adjacent:
                if v2:
                    self._use_once("sneak", attacker)
                self.turn.sneak_attack_used = True
                amt, ids = self._roll_damage(f"{attacker.sneak_attack_dice}d6", crit, "damage: Sneak Attack",
                                             attacker.id, target.id)
                parts[atk.damage_type] += amt
                ev["damage_rolls"] += ids
                ev["sneak_attack"] = True
        ev["damage"] = self.apply_damage(target, parts, critical=crit, source=attacker.id)
        dealt = ev["damage"]["total"] > 0
        self._apply_mastery(attacker, target, atk, mastery, dealt, ev)
        if atk.on_hit and target.standing:
            self._apply_on_hit(attacker, target, atk.on_hit, ev)
        return ev

    def _apply_mastery(self, attacker: Creature, target: Creature, atk: Attack, mastery: str | None,
                       dealt: bool, ev: dict) -> None:
        if not mastery or not target.standing:
            return
        ev["mastery"] = mastery
        if mastery == "vex" and dealt:
            attacker.add_effect(Effect("vex", attacker.id, {"target": target.id}, expires=("end", attacker.id, 1)))
        elif mastery == "sap":
            target.add_effect(Effect("sapped", attacker.id, {}, expires=("start", attacker.id, 0)))
        elif mastery == "slow" and dealt:
            target.add_effect(Effect("slowed", attacker.id, {"speed_penalty": 10}, expires=("start", attacker.id, 0)))
        elif mastery == "topple":
            dc = 8 + attacker.mod(atk.ability or "str") + attacker.proficiency
            rec = saving_throw(target, self.dice, "con", dc, purpose="Topple", source=attacker.id)
            ev["topple"] = {"roll": rec.id, "success": rec.success}
            if not rec.success:
                target.add_condition("prone", source=attacker.id)
        elif mastery == "push" and size_index(target.size) <= size_index("large"):
            ev["push"] = self._push(attacker, target, 10)

    def _push(self, source: Creature, target: Creature, feet: int) -> list[int]:
        dx = (target.pos[0] > source.pos[0]) - (target.pos[0] < source.pos[0])
        dy = (target.pos[1] > source.pos[1]) - (target.pos[1] < source.pos[1])
        if dx == 0 and dy == 0:
            dx = 1
        occ = self.occupied(exclude=target.id)
        pos = target.pos
        for _ in range(feet // 5):
            nxt = (pos[0] + dx, pos[1] + dy)
            if nxt in occ:
                break
            pos = nxt
        target.pos = pos
        return list(pos)

    def _apply_on_hit(self, attacker: Creature, target: Creature, on_hit: dict, ev: dict) -> None:
        cond = on_hit.get("condition")
        if not cond:
            return
        if "max_size" in on_hit and size_index(target.size) > size_index(on_hit["max_size"]):
            return
        if "save" in on_hit:
            rec = saving_throw(target, self.dice, on_hit["save"], on_hit["dc"], purpose=f"{cond} save",
                               source=attacker.id, against={cond})
            ev["on_hit_save"] = {"roll": rec.id, "success": rec.success}
            if rec.success:
                return
        if target.add_condition(cond, source=attacker.id):
            ev["condition_applied"] = cond

    # ============================================================ spells
    def _spend_slot(self, c: Creature, level: int) -> None:
        slot = c.spellcasting["slots"][str(level)]
        if slot["current"] <= 0:
            raise EngineError(f"No level-{level} slots left")
        slot["current"] -= 1

    def _spell_cast_economy(self, c: Creature, sp: dict, uses_slot: bool) -> None:
        ct = sp["casting_time"]
        if ct == "action":
            if self.turn.actions <= 0:
                raise EngineError("No action left")
            if uses_slot and self.turn.bonus_slot_spell_cast:
                raise EngineError("Already cast a bonus-action spell with a slot this turn")
        elif ct == "bonus_action":
            if not self.turn.bonus_action:
                raise EngineError("No bonus action left")
            if uses_slot and self.turn.slot_spell_cast:
                raise EngineError("Already cast a spell with a slot this turn")
        else:
            raise EngineError(f"{sp['name']} can't be cast in combat ({ct})")

    def area_targets(self, c: Creature, spell_id: str, aim: tuple[int, int]) -> tuple[set, list[Creature]]:
        sp = data.spell(spell_id)
        area = sp["area"]
        squares = grid.area_squares(area["shape"], area["size_ft"], c.pos, tuple(aim))
        hit = [o for o in self.creatures.values() if not o.dead and o.id != c.id and o.pos in squares]
        return squares, hit

    def cast(self, c: Creature, spell_id: str, targets: list[str], level: int | None = None,
             free: bool = False, toward: list[int] | None = None) -> dict:
        sp = data.spell(spell_id)
        if not c.knows_spell(spell_id):
            raise EngineError(f"{c.id} doesn't have {sp['name']} prepared")
        base = sp["level"]
        level = base if level is None else level
        if level < base:
            raise EngineError("Can't cast below the spell's level")
        uses_slot = base > 0 and not free
        if free:
            fc = c.spellcasting.get("free_casts", {}).get(spell_id)
            if not fc or fc["current"] <= 0 or level != base:
                raise EngineError(f"No free cast of {sp['name']} available")
        elif base > 0 and c.slots_available(level) <= 0:
            raise EngineError(f"No level-{level} slot left")
        self._spell_cast_economy(c, sp, uses_slot)
        area_sq = None
        if sp.get("area"):
            if toward is None:
                if not targets:
                    raise EngineError(f"{sp['name']} needs an aim point ('toward')")
                toward = list(self.get(targets[0]).pos)
            if sp["area"]["shape"] == "sphere" and distance_ft(c.pos, tuple(toward)) > sp["range_ft"]:
                raise EngineError(f"Aim point is out of range of {sp['name']}")
            area_sq, tgt = self.area_targets(c, spell_id, tuple(toward))
            targets = [t.id for t in tgt]
        tgt = [self.get(t) for t in targets]
        if sp.get("self_only"):
            tgt = [c]
        max_t = sp.get("max_targets")
        if max_t:
            max_t += sp.get("upcast_targets", 0) * (level - base)
            if len(tgt) > max_t:
                raise EngineError(f"{sp['name']} affects at most {max_t} targets")
        reach = max(5, sp["range_ft"])
        for t in tgt:
            if area_sq is None and t.id != c.id and self.dist(c, t) > reach:
                raise EngineError(f"{t.id} is out of range of {sp['name']} ({reach} ft)")
        if sp["kind"] in ("attack", "save", "auto", "heal") and not tgt and area_sq is None:
            raise EngineError(f"{sp['name']} needs a target")

        # Commit costs.
        if sp["casting_time"] == "action":
            self.turn.actions -= 1
            if uses_slot:
                self.turn.slot_spell_cast = True
        else:
            self.turn.bonus_action = False
            if uses_slot:
                self.turn.bonus_slot_spell_cast = True
                self.turn.slot_spell_cast = True
        if free:
            c.spellcasting["free_casts"][spell_id]["current"] -= 1
        elif uses_slot:
            self._spend_slot(c, level)
        if sp.get("concentration"):
            self.end_concentration(c, f"cast {sp['name']}")
            c.concentration = spell_id
        if any(t.team != c.team for t in tgt) and c.effect("sanctuary"):
            c.remove_effects(lambda e: e.name == "sanctuary")
            self.emit("effect_end", target=c.id, effect="sanctuary", reason="warded creature cast at an enemy")

        ev = self.emit("cast", actor=c.id, spell=spell_id, level=level, targets=[t.id for t in tgt],
                       fx=sp.get("fx"), results=[])
        if area_sq is not None:
            ev["area"] = sorted([list(q) for q in area_sq])
            ev["toward"] = list(toward)
            ev["allies_hit"] = [t.id for t in tgt if t.team == c.team]
        kind = sp["kind"]
        if kind == "attack":
            self._cast_attack(c, sp, level, tgt[0], ev)
        elif kind == "save":
            self._cast_save(c, sp, level, tgt, ev)
        elif kind == "auto":
            self._cast_auto(c, sp, level, tgt, ev)
        elif kind == "heal":
            self._cast_heal(c, sp, level, tgt, ev)
        elif kind == "buff":
            self._cast_buff(c, sp, level, tgt, ev)
        else:
            self._cast_utility(c, sp, tgt, ev)
        return ev

    def _spell_damage_notation(self, c: Creature, sp: dict, level: int) -> str:
        spec = DiceSpec.parse(sp["damage"])
        if sp.get("cantrip_scaling"):
            spec = spec.scaled(c.cantrip_dice_multiplier())
        if sp.get("upcast_dice") and level > sp["level"]:
            spec = spec.plus_dice(sp["upcast_dice"] * (level - sp["level"]))
        return str(spec)

    def _cast_attack(self, c: Creature, sp: dict, level: int, t: Creature, ev: dict) -> None:
        self._check_target(c, t)
        ranged = sp.get("attack") == "ranged"
        if self._sanctuary_blocks(c, t):
            ev["results"].append({"target": t.id, "blocked": "sanctuary"})
            return
        rec, hit, crit, _ = self._attack_roll(c, t, c.spell_attack_bonus, ranged, False, f"spell attack: {sp['name']}")
        r = {"target": t.id, "roll": rec.id, "hit": hit, "critical": crit, "overlay": rec.overlay_text()}
        notation = self._spell_damage_notation(c, sp, level)
        if hit:
            amt, ids = self._roll_damage(notation, crit, f"damage: {sp['name']}", c.id, t.id)
            r["damage_rolls"] = ids
            r["damage"] = self.apply_damage(t, {sp["damage_type"]: amt}, critical=crit, source=c.id)
            on_hit = sp.get("on_hit")
            if on_hit and t.standing:
                self._spell_on_hit(c, t, on_hit)
                r["effect"] = on_hit["effect"]
        elif sp["level"] == 0 and "potent_cantrip" in c.features:
            amt, ids = self._roll_damage(notation, False, f"damage: {sp['name']} (Potent Cantrip)", c.id, t.id)
            r["damage_rolls"] = ids
            r["damage"] = self.apply_damage(t, {sp["damage_type"]: amt // 2}, source=c.id)
        ev["results"].append(r)

    def _spell_on_hit(self, c: Creature, t: Creature, on_hit: dict) -> None:
        name = on_hit["effect"]
        if name == "slowed":
            t.add_effect(Effect("slowed", c.id, {"speed_penalty": on_hit.get("speed_penalty", 10)},
                                expires=("start", c.id, 0)))
        elif name == "no_opportunity_attacks":
            t.add_effect(Effect("no_opportunity_attacks", c.id, {}, expires=("start", t.id, 0)))
        elif name == "guiding_bolt":
            t.add_effect(Effect("guiding_bolt", c.id, {}, expires=("end", c.id, 1)))

    def _cast_save(self, c: Creature, sp: dict, level: int, tgt: list[Creature], ev: dict) -> None:
        notation = self._spell_damage_notation(c, sp, level)
        dmg_rec = self.dice.roll(notation, purpose=f"damage: {sp['name']}", actor=c.id)
        ev["damage_roll"] = dmg_rec.id
        dc = c.spell_save_dc
        for t in tgt:
            if t.dead:
                continue
            adv = sp["save"] == "dex" and bool(t.effect("dodge"))
            rec = saving_throw(t, self.dice, sp["save"], dc, advantage=adv, purpose=f"{sp['name']} save",
                               source=c.id, against={"spell"})
            r = {"target": t.id, "roll": rec.id, "saved": rec.success, "dc": dc, "overlay": rec.overlay_text()}
            if rec.success:
                if sp.get("half_on_save"):
                    amount = dmg_rec.total // 2
                elif sp["level"] == 0 and "potent_cantrip" in c.features:
                    amount = dmg_rec.total // 2
                else:
                    amount = 0
            else:
                amount = dmg_rec.total
            if amount:
                r["damage"] = self.apply_damage(t, {sp["damage_type"]: amount}, source=c.id)
            if not rec.success and sp.get("on_fail", {}).get("push_ft") and t.standing \
                    and size_index(t.size) <= size_index("large"):
                r["push"] = self._push(c, t, sp["on_fail"]["push_ft"])
            ev["results"].append(r)

    def _cast_auto(self, c: Creature, sp: dict, level: int, tgt: list[Creature], ev: dict) -> None:
        darts = sp["darts"] + sp.get("upcast_darts", 0) * (level - sp["level"])
        shielded = set()
        for t in tgt:
            if t.id not in shielded and self.auto_reactions and self.reactions.get(t.id) and t.conscious \
                    and t.knows_spell("shield") and t.lowest_slot_at_least(1) is not None:
                slot = t.lowest_slot_at_least(1)
                self._spend_slot(t, slot)
                self.reactions[t.id] = False
                t.add_effect(Effect("shield_spell", t.id, {"ac_bonus": 5}, expires=("start", t.id, 0)))
                self.emit("reaction", actor=t.id, reaction="shield", slot=slot, ac=t.ac)
                shielded.add(t.id)
        # Darts are assigned round-robin over the listed targets (repeat an id to focus).
        for i in range(darts):
            t = tgt[i % len(tgt)]
            if t.id in shielded or t.dead:
                ev["results"].append({"target": t.id, "dart": i + 1, "blocked": "shield" if t.id in shielded else "dead"})
                continue
            amt, ids = self._roll_damage(sp["dart_damage"], False, f"damage: {sp['name']} dart {i + 1}", c.id, t.id)
            ev["results"].append({"target": t.id, "dart": i + 1, "damage_rolls": ids,
                                  "damage": self.apply_damage(t, {sp["damage_type"]: amt}, source=c.id)})

    def _cast_heal(self, c: Creature, sp: dict, level: int, tgt: list[Creature], ev: dict) -> None:
        spec = DiceSpec.parse(sp["heal"])
        if level > sp["level"]:
            spec = spec.plus_dice(sp.get("upcast_dice", 0) * (level - sp["level"]))
        bonus = c.spell_mod if sp.get("add_mod") else 0
        if "disciple_of_life" in c.features and sp["level"] > 0:
            bonus += 2 + level
        for t in tgt:
            rec = self.dice.roll(spec, purpose=f"healing: {sp['name']}", actor=c.id, target=t.id, extra_modifier=bonus)
            res = t.heal(rec.total)
            ev["results"].append({"target": t.id, "roll": rec.id, **res})

    def _cast_buff(self, c: Creature, sp: dict, level: int, tgt: list[Creature], ev: dict) -> None:
        b = dict(sp["buff"])
        name = b.pop("effect")
        expires = None
        if b.pop("expires", None) == "start_of_caster_turn":
            expires = ("start", c.id, 0)
        if name == "sanctuary":
            b["dc"] = c.spell_save_dc
        for t in tgt:
            eff = Effect(name, c.id, dict(b), expires=expires, rounds_left=sp.get("duration_rounds"),
                         concentration=bool(sp.get("concentration")))
            t.add_effect(eff)
            ev["results"].append({"target": t.id, "effect": name})

    def _cast_utility(self, c: Creature, sp: dict, tgt: list[Creature], ev: dict) -> None:
        if sp.get("special") == "stabilize":
            for t in tgt:
                if t.hp == 0 and not t.dead:
                    t.stable = True
                    t.death_saves = {"successes": 0, "failures": 0}
                    ev["results"].append({"target": t.id, "stabilized": True})
                else:
                    raise EngineError(f"{t.id} isn't dying")

    # ======================================================= opportunity
    def _opportunity_attacks(self, mover: Creature, start: tuple[int, int], end: tuple[int, int]) -> None:
        if self.turn.disengaged:
            return
        for e in self.enemies_of(mover):
            if not self.reactions.get(e.id) or e.incapacitated or e.effect("no_opportunity_attacks"):
                continue
            melee = [a for a in e.attacks if a.type == "melee"]
            if not melee:
                continue
            atk = max(melee, key=lambda a: DiceSpec.parse(a.damage).average)
            if distance_ft(start, e.pos) <= atk.reach_ft < distance_ft(end, e.pos):
                self.reactions[e.id] = False
                saved = mover.pos
                mover.pos = start  # the attack happens as the mover leaves reach
                self.emit("reaction", actor=e.id, reaction="opportunity_attack", target=mover.id)
                self.resolve_weapon_attack(e, mover, atk, opportunity=True)
                mover.pos = saved
                if not mover.standing:
                    mover.pos = start
                    return

    # ============================================================ intents
    def act(self, intent: dict) -> list[dict]:
        """Execute one intent for the current creature. Returns new events."""
        if not self.started or self.finished:
            raise EngineError("Encounter is not running")
        c = self.current
        if intent.get("actor", c.id) != c.id:
            raise EngineError(f"It is {c.id}'s turn, not {intent.get('actor')}'s")
        t = intent.get("type")
        if t != "end_turn" and not self.can_act(c):
            raise EngineError(f"{c.id} can't act (down or incapacitated)")
        mark = len(self.events)
        handler = getattr(self, f"_do_{t}", None)
        if handler is None:
            raise EngineError(f"Unknown intent type {t!r}")
        handler(c, intent)
        if self.is_over() and t != "end_turn":
            self._finish()
        return self.events[mark:]

    def _use_action(self, c: Creature, bonus_ok: str | None = None, intent: dict | None = None) -> str:
        """Spend an action, or a bonus action if a feature allows (returns which)."""
        if intent and intent.get("bonus"):
            if not bonus_ok or bonus_ok not in c.traits | c.features:
                raise EngineError("No feature lets this be a bonus action")
            if not self.turn.bonus_action:
                raise EngineError("No bonus action left")
            self.turn.bonus_action = False
            return "bonus_action"
        if self.turn.actions <= 0:
            raise EngineError("No action left")
        self.turn.actions -= 1
        return "action"

    def _do_end_turn(self, c: Creature, intent: dict) -> None:
        self.end_turn()

    def _do_move(self, c: Creature, intent: dict) -> None:
        """Move along a path (given, or the cheapest one found). Opportunity
        attacks are checked at every step; a creature that drops stops there."""
        to = tuple(intent["to"])
        if not self.endable(c, to):
            raise EngineError(f"Square {list(to)} is occupied or blocked")
        if intent.get("path"):
            path = [tuple(p) for p in intent["path"]]
            if path[0] != c.pos:
                path = [c.pos] + path
            if path[-1] != to:
                raise EngineError("Path must end at 'to'")
            for a, b in zip(path, path[1:]):
                if grid.chebyshev(a, b) != 1 or not self.passable(c, b):
                    raise EngineError(f"Illegal step {list(a)} -> {list(b)}")
            cost = sum(self.step_cost(c, b) for b in path[1:])
        else:
            tree = self.reach_map(c)
            path = grid.path_to(tree, to)
            if path is None:
                raise EngineError(f"Can't reach {list(to)} with {self.turn.movement} ft of movement")
            cost = tree[to][0]
        if cost > self.turn.movement:
            raise EngineError(f"Move costs {cost} ft; {self.turn.movement} ft left")
        start = c.pos
        ev = self.emit("move", actor=c.id, frm=list(start), to=list(to), cost=cost, path=[list(p) for p in path])
        walked = [start]
        for a, b in zip(path, path[1:]):
            self.turn.movement -= self.step_cost(c, b)
            c.pos = b
            walked.append(b)
            self._opportunity_attacks(c, a, b)
            if not c.standing or c.pos != b:
                break
        if c.pos != to:
            ev["interrupted_at"] = list(c.pos)
            ev["path"] = [list(p) for p in walked if p != walked[-1]] + [list(c.pos)]

    def _do_stand_up(self, c: Creature, intent: dict) -> None:
        if not c.has_condition("prone"):
            raise EngineError("Not prone")
        cost = c.current_speed // 2
        if self.turn.movement < cost:
            raise EngineError("Not enough movement to stand")
        self.turn.movement -= cost
        c.remove_condition("prone")
        self.emit("stand_up", actor=c.id, cost=cost)

    def _attacks_per_action(self, c: Creature) -> int:
        if c.multiattack:
            return len(c.multiattack)
        return 1 + c.extra_attacks

    def _do_attack(self, c: Creature, intent: dict) -> None:
        atk = c.attack_by_id(intent["attack"])
        target = self.get(intent["target"])
        if self.turn.attacks_left <= 0:
            if self.turn.actions <= 0:
                raise EngineError("No action left to attack with")
            # Validate before spending the action.
            self._check_target(c, target)
            self._range_check(c, target, atk)
            if c.multiattack and atk.id.split(":")[0] not in c.multiattack:
                pass  # any listed attack may be used once multiattack doesn't fit (ranged fallback)
            self.turn.actions -= 1
            self.turn.attacks_left = self._attacks_per_action(c)
        self.turn.attacks_left -= 1
        self.resolve_weapon_attack(c, target, atk)

    def _do_cast(self, c: Creature, intent: dict) -> None:
        if self.turn.attacks_left > 0 and self.turn.actions <= 0 and data.spell(intent["spell"])["casting_time"] == "action":
            raise EngineError("Action already used for attacks")
        self.cast(c, intent["spell"], intent.get("targets", []), intent.get("level"), bool(intent.get("free")),
                  intent.get("toward"))

    def _do_dash(self, c: Creature, intent: dict) -> None:
        how = self._use_action(c, "cunning_action" if "cunning_action" in c.features else None, intent)
        self.turn.movement += c.current_speed
        self.emit("dash", actor=c.id, via=how)

    def _do_disengage(self, c: Creature, intent: dict) -> None:
        feature = "nimble_escape" if "nimble_escape" in c.traits else "cunning_action"
        how = self._use_action(c, feature, intent)
        self.turn.disengaged = True
        self.emit("disengage", actor=c.id, via=how)

    def _do_dodge(self, c: Creature, intent: dict) -> None:
        self._use_action(c)
        c.add_effect(Effect("dodge", c.id, {}, expires=("start", c.id, 0)))
        self.emit("dodge", actor=c.id)

    def _do_hide(self, c: Creature, intent: dict) -> None:
        feature = "nimble_escape" if "nimble_escape" in c.traits else "cunning_action"
        how = self._use_action(c, feature, intent)
        rec = ability_check(c, self.dice, skill="stealth", dc=15, purpose="hide")
        if rec.success:
            c.add_effect(Effect("hidden", c.id, {"stealth": rec.total}))
        self.emit("hide", actor=c.id, via=how, roll=rec.id, success=rec.success)

    def _do_help(self, c: Creature, intent: dict) -> None:
        target = self.get(intent["target"])
        if target.team == c.team:
            raise EngineError("Help in combat targets an enemy within 5 ft (to aid an ally's attack)")
        if self.dist(c, target) > 5:
            raise EngineError("Help requires the enemy to be within 5 ft")
        self._use_action(c)
        target.add_effect(Effect("help_target", c.id, {"by": c.id}, expires=("start", c.id, 0)))
        self.emit("help", actor=c.id, target=target.id)

    def _do_second_wind(self, c: Creature, intent: dict) -> None:
        res = c.resources.get("second_wind")
        if not res or res["current"] <= 0:
            raise EngineError("No Second Wind uses left")
        if not self.turn.bonus_action:
            raise EngineError("No bonus action left")
        self.turn.bonus_action = False
        res["current"] -= 1
        rec = self.dice.roll("1d10", purpose="Second Wind", actor=c.id, extra_modifier=c.level)
        out = c.heal(rec.total)
        self.emit("second_wind", actor=c.id, roll=rec.id, **out)

    def _do_action_surge(self, c: Creature, intent: dict) -> None:
        res = c.resources.get("action_surge")
        if not res or res["current"] <= 0:
            raise EngineError("No Action Surge uses left")
        if self.turn.action_surge_used:
            raise EngineError("Action Surge already used this turn")
        res["current"] -= 1
        self.turn.action_surge_used = True
        self.turn.actions += 1
        self.emit("action_surge", actor=c.id)

    def _do_use_item(self, c: Creature, intent: dict) -> None:
        item = intent["item"]
        target = self.get(intent.get("target", c.id))
        if c.inventory.get(item, 0) <= 0:
            raise EngineError(f"{c.id} has no {item}")
        info = data.items().get(item, {})
        if "heal" not in info:
            raise EngineError(f"{item} can't be used in combat")
        if self.dist(c, target) > 5:
            raise EngineError("Target must be within 5 ft")
        if target.id == c.id:
            if not self.turn.bonus_action:
                raise EngineError("No bonus action left")
            self.turn.bonus_action = False  # house rule: drink your own potion as a bonus action
        else:
            self._use_action(c)
        c.inventory[item] -= 1
        rec = self.dice.roll(info["heal"], purpose=f"healing: {info['name']}", actor=c.id, target=target.id)
        out = target.heal(rec.total)
        self.emit("use_item", actor=c.id, item=item, target=target.id, roll=rec.id, **out)

    def _do_stabilize(self, c: Creature, intent: dict) -> None:
        target = self.get(intent["target"])
        if target.hp > 0 or target.dead or target.stable:
            raise EngineError(f"{target.id} doesn't need stabilizing")
        if self.dist(c, target) > 5:
            raise EngineError("Target must be within 5 ft")
        self._use_action(c)
        rec = ability_check(c, self.dice, skill="medicine", dc=10, purpose="stabilize")
        if rec.success:
            target.stable = True
            target.death_saves = {"successes": 0, "failures": 0}
        self.emit("stabilize", actor=c.id, target=target.id, roll=rec.id, success=rec.success)

    # ======================================================= action menu
    def _move_options(self, c: Creature) -> list[dict]:
        """Tactical destinations: engage each enemy, advance, fall back, guard an ally."""
        tree = self.reach_map(c)
        ends = [sq for sq in tree if sq != c.pos and self.endable(c, sq)]
        if not ends:
            return []
        enemies = self.enemies_of(c)
        allies = [a for a in self.allies_of(c) if not a.incapacitated]
        reach = max((a.reach_ft for a in c.attacks if a.type == "melee" and a.id != "unarmed"), default=5)
        out: list[dict] = []
        prov_cache: dict = {}

        def prov(sq):
            if sq not in prov_cache:
                prov_cache[sq] = self.provokers(c, grid.path_to(tree, sq))
            return prov_cache[sq]

        def opt(sq, label, tags):
            p = prov(sq)
            text = f"{label} ({tree[sq][0]} ft" + (f", provokes {', '.join(p)}" if p else "") + ")"
            return {"intent": {"type": "move", "to": list(sq)}, "label": text, "cost": f"{tree[sq][0]} ft",
                    "tags": tags, "provokes": p}

        for e in enemies:
            if self.dist(c, e) <= reach:
                continue
            cands = [sq for sq in ends if distance_ft(sq, e.pos) <= reach]
            if not cands:
                continue

            def flank(sq, e=e):
                return self.options["flanking"] and any(al.pos == (2 * e.pos[0] - sq[0], 2 * e.pos[1] - sq[1])
                                                        for al in allies)
            best = min(cands, key=lambda sq: (len(prov(sq)), not flank(sq), tree[sq][0], sq))
            tags = ["engage"]
            if flank(best):
                tags.append("flank")
            if c.sneak_attack_dice and (flank(best) or any(distance_ft(al.pos, e.pos) <= 5 for al in allies)):
                tags.append("sneak_attack")
            o = opt(best, f"Move to engage {e.name} ({e.id}) at {list(best)}", tags)
            o["target"] = e.id
            out.append(o)
        if enemies and all(self.dist(c, e) > reach for e in enemies) and not out:
            near = min(enemies, key=lambda e: (self.dist(c, e), e.id))
            best = min(ends, key=lambda sq: (distance_ft(sq, near.pos), tree[sq][0], sq))
            if distance_ft(best, near.pos) < self.dist(c, near):
                out.append(opt(best, f"Advance toward {near.name} ({near.id}) to {list(best)}", ["advance"]))
        ranged = [a for a in c.attacks if a.type == "ranged" and a.range]
        if self.options.get("tactics", 1) >= 2 and ranged and enemies:
            # Tactics 2: a shooter beyond normal range can step in rather than shoot with disadvantage.
            normal = max(a.range[0] for a in ranged)

            def keep_off(sq):
                return min(distance_ft(sq, x.pos) for x in enemies)
            for e in enemies:
                if self.dist(c, e) <= normal:
                    continue
                cands = [sq for sq in ends if distance_ft(sq, e.pos) <= normal]
                if not cands:
                    continue
                best = min(cands, key=lambda sq: (len(prov(sq)), keep_off(sq) <= 5, -keep_off(sq), tree[sq][0], sq))
                o = opt(best, f"Close to {normal} ft of {e.name} ({e.id}) at {list(best)}", ["close_range"])
                o["target"] = e.id
                out.append(o)
        if enemies:
            def safety(sq):
                return min(distance_ft(sq, e.pos) for e in enemies)
            now = min(self.dist(c, e) for e in enemies)
            best = max(ends, key=lambda sq: (safety(sq), -len(prov(sq)), -tree[sq][0], sq))
            if safety(best) > now:
                out.append(opt(best, f"Fall back to {list(best)}, {safety(best)} ft from the nearest enemy", ["retreat"]))
            for al in allies:
                threats = [e for e in enemies if self.dist(al, e) <= 10]
                if not threats:
                    continue
                t = min(threats, key=lambda e: (self.dist(al, e), e.id))
                cands = [sq for sq in ends if distance_ft(sq, al.pos) <= 5 and distance_ft(sq, t.pos) <= reach]
                if cands:
                    best = min(cands, key=lambda sq: (len(prov(sq)), tree[sq][0], sq))
                    o = opt(best, f"Step in to guard {al.name} and engage {t.id}", ["guard", "engage"])
                    o["target"] = t.id
                    out.append(o)
        return out

    def legal_actions(self) -> list[dict]:
        """Every legal intent for the current creature, with labels and odds."""
        c = self.current
        out: list[dict] = []
        if self.finished or not self.can_act(c):
            return [{"intent": {"type": "end_turn"}, "label": "End turn", "cost": "free"}]
        ts = self.turn
        can_attack = ts.attacks_left > 0 or ts.actions > 0
        enemies = self.enemies_of(c)
        if can_attack:
            for atk in c.attacks:
                for e in enemies:
                    try:
                        long_range = self._range_check(c, e, atk)
                    except EngineError:
                        continue
                    if self._ammo_key(c, atk) and c.inventory.get(self._ammo_key(c, atk), 0) <= 0:
                        continue
                    adv, dis, why = self._attack_modifiers(c, e, atk.type == "ranged", long_range)
                    out.append({"intent": {"type": "attack", "attack": atk.id, "target": e.id},
                                "label": f"{atk.name} → {e.name} ({e.id})", "cost": "attack",
                                "hit_chance": round(hit_chance(atk.to_hit, e.ac, adv, dis), 2),
                                "damage": atk.damage, "notes": why})
        if ts.movement > 0:
            out += self._move_options(c)
        if c.spellcasting:
            out += self._spell_options(c)
        if ts.actions > 0:
            for t in ("dash", "disengage", "dodge"):
                out.append({"intent": {"type": t}, "label": t.capitalize(), "cost": "action"})
            out.append({"intent": {"type": "hide"}, "label": "Hide (Stealth DC 15)", "cost": "action"})
            for e in enemies:
                if self.dist(c, e) <= 5:
                    out.append({"intent": {"type": "help", "target": e.id},
                                "label": f"Help an ally against {e.id}", "cost": "action"})
            for a in self.allies_of(c, standing_only=False):
                if a.hp == 0 and not a.dead and not a.stable and self.dist(c, a) <= 5:
                    out.append({"intent": {"type": "stabilize", "target": a.id},
                                "label": f"Stabilize {a.name} (Medicine DC 10)", "cost": "action"})
        if ts.bonus_action:
            bonus_feature = "nimble_escape" if "nimble_escape" in c.traits else (
                "cunning_action" if "cunning_action" in c.features else None)
            if bonus_feature:
                for t in ("disengage", "hide") + (("dash",) if bonus_feature == "cunning_action" else ()):
                    out.append({"intent": {"type": t, "bonus": True}, "label": f"{t.capitalize()} (bonus action)",
                                "cost": "bonus_action"})
            sw = c.resources.get("second_wind")
            if sw and sw["current"] > 0 and c.hp < c.max_hp:
                out.append({"intent": {"type": "second_wind"}, "label": f"Second Wind (1d10+{c.level})",
                            "cost": "bonus_action"})
            if c.inventory.get("potion_of_healing", 0) > 0 and c.hp < c.max_hp:
                out.append({"intent": {"type": "use_item", "item": "potion_of_healing", "target": c.id},
                            "label": "Drink a Potion of Healing", "cost": "bonus_action"})
        surge = c.resources.get("action_surge")
        if surge and surge["current"] > 0 and not ts.action_surge_used:
            out.append({"intent": {"type": "action_surge"}, "label": "Action Surge (+1 action)", "cost": "free"})
        if c.has_condition("prone") and ts.movement >= c.current_speed // 2:
            out.append({"intent": {"type": "stand_up"}, "label": "Stand up", "cost": "half movement"})
        out.append({"intent": {"type": "end_turn"}, "label": "End turn", "cost": "free"})
        return out

    def _spell_options(self, c: Creature) -> list[dict]:
        out = []
        sc = c.spellcasting
        known = list(dict.fromkeys(sc.get("cantrips", []) + sc.get("prepared", []) + list(sc.get("free_casts", {}))))
        for sid in known:
            sp = data.spell(sid)
            if sp["casting_time"] not in ("action", "bonus_action"):
                continue
            ct = sp["casting_time"]
            if ct == "action" and (self.turn.actions <= 0 or (self.turn.attacks_left > 0 and self.turn.actions <= 0)):
                continue
            if ct == "bonus_action" and not self.turn.bonus_action:
                continue
            free = False
            level = sp["level"]
            if level > 0:
                lowest = c.lowest_slot_at_least(level)
                fc = sc.get("free_casts", {}).get(sid)
                if fc and fc["current"] > 0:
                    free = True
                elif lowest is None:
                    continue
                else:
                    level = lowest
                if ct == "action" and self.turn.bonus_slot_spell_cast and not free:
                    continue
                if ct == "bonus_action" and self.turn.slot_spell_cast and not free:
                    continue
            reach = max(5, sp["range_ft"])
            kind = sp["kind"]
            base = {"type": "cast", "spell": sid}
            if level != sp["level"] or level:
                base["level"] = level
            if free:
                base["free"] = True
            cost = ct
            if kind in ("attack", "save", "auto"):
                in_range = [e for e in self.enemies_of(c) if self.dist(c, e) <= reach]
                if not in_range:
                    continue
                if sp.get("area"):
                    seen = set()
                    for aim in grid.aims(c.pos, [e.pos for e in self.enemies_of(c)]):
                        _, hit = self.area_targets(c, sid, aim)
                        foes = sorted(h.id for h in hit if h.team != c.team and h.standing)
                        friends = sorted(h.id for h in hit if h.team == c.team)
                        key = (tuple(foes), tuple(friends))
                        if not foes or key in seen:
                            continue
                        seen.add(key)
                        label = f"{sp['name']} toward {list(aim)}: hits {', '.join(foes)}"
                        if friends:
                            label += f" - ALSO HITS ALLIES {', '.join(friends)}"
                        out.append({"intent": {**base, "toward": list(aim)}, "label": label, "cost": cost,
                                    "enemies_hit": foes, "allies_hit": friends})
                else:
                    for e in in_range:
                        opt = {"intent": {**base, "targets": [e.id]}, "label": f"{sp['name']} → {e.id}", "cost": cost}
                        if kind == "attack":
                            adv, dis, _ = self._attack_modifiers(c, e, sp.get("attack") == "ranged", False)
                            opt["hit_chance"] = round(hit_chance(c.spell_attack_bonus, e.ac, adv, dis), 2)
                        out.append(opt)
            elif kind == "heal":
                for a in self.allies_of(c, include_self=True, standing_only=False):
                    if not a.dead and a.hp < a.max_hp and self.dist(c, a) <= reach:
                        out.append({"intent": {**base, "targets": [a.id]},
                                    "label": f"{sp['name']} → {a.name} ({a.hp}/{a.max_hp} HP)", "cost": cost})
            elif kind == "buff":
                if sp.get("self_only"):
                    continue
                allies = [a for a in self.allies_of(c, include_self=True) if self.dist(c, a) <= reach
                          and not a.effect(sp["buff"]["effect"])]
                n = sp.get("max_targets", 1)
                if allies:
                    out.append({"intent": {**base, "targets": [a.id for a in allies[:n]]},
                                "label": f"{sp['name']} on {', '.join(a.id for a in allies[:n])}", "cost": cost})
            elif sp.get("special") == "stabilize":
                for a in self.allies_of(c, standing_only=False):
                    if a.hp == 0 and not a.dead and not a.stable and self.dist(c, a) <= reach:
                        out.append({"intent": {**base, "targets": [a.id]}, "label": f"Spare the Dying → {a.id}",
                                    "cost": cost})
        return out

    # ================================================================ run
    def run(self, policy: Policy, max_rounds: int = 30) -> dict:
        """Run to the end. ``policy(encounter, creature)`` returns either one
        intent (called again until it returns ``end_turn``) or a list of
        intents for the whole turn (executed in order, then the turn ends)."""
        if not self.started:
            self.start()
        guard = 0
        while not self.finished and self.round <= max_rounds:
            guard += 1
            if guard > 5000:
                raise RuntimeError("Encounter loop guard tripped")
            c = self.current
            steps = 0
            while self.can_act(c) and not self.finished and steps < 20:
                steps += 1
                out = policy(self, c)
                batch = out if isinstance(out, list) else [out]
                stop = isinstance(out, list)
                for intent in batch:
                    if not intent or intent.get("type") == "end_turn" or self.finished:
                        stop = True
                        break
                    try:
                        self.act(intent)
                    except EngineError as exc:
                        self.emit("illegal_intent", actor=c.id, intent=intent, reason=str(exc))
                        stop = True
                        break
                if stop:
                    break
            if not self.finished:
                self.end_turn()
        if not self.finished:
            self.emit("encounter_timeout", rounds=self.round)
        return self.result()

    def result(self) -> dict:
        end = next((e for e in reversed(self.events) if e["t"] == "encounter_end"), None)
        return {
            "name": self.name,
            "seed": self.dice.seed,
            "finished": self.finished,
            "winner": end["winner"] if end else None,
            "rounds": self.round,
            "xp": end["xp"] if end else 0,
            "combatants": [c.summary() for c in self.creatures.values()],
            "events": self.events,
            "rolls": self.dice.export_log(),
        }
