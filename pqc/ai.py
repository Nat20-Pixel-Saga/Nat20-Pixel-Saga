"""Deterministic tactical policy, by role.

Used for tests and demos, and as the fallback whenever the tactical model
returns an unusable choice. It only ever picks from ``legal_actions()`` and
never touches dice. One intent per call; the runner calls again until the
creature ends its turn.

Roles
-----
* tank (fighters)       — steps in front of the most threatened ally, engages, holds the line.
* skirmisher (rogues)   — sets up Sneak Attack: shoots targets an ally is engaging, avoids melee,
                          flanks when the flanking rule is on, uses Cunning Action to slip away.
* artillery (wizards)   — keeps distance, aims areas that hit 2+ foes and no friends, uses
                          Shocking Grasp to escape melee without an opportunity attack.
* support (clerics)     — revives and heals, Blesses early, stays near the line but out of reach.
* brute (most monsters) — closes on the softest reachable target and keeps attacking.
* archer (ranged foes)  — shoots, and Disengages away from melee when it can.

Tactics 2 (encounter option ``tactics``, on from the episode in production/features.json):
brutes with Nimble Escape slip past an armoured defender to a softer target and, once
bloodied, hit and Disengage out of reach; shooters step in to normal range rather than
shoot with disadvantage from long range.
"""
from __future__ import annotations

from .combat import Encounter
from .creature import Creature
from .rules import distance_ft

PC_ROLES = {"fighter": "tank", "rogue": "skirmisher", "wizard": "artillery", "cleric": "support"}


def role_of(c: Creature) -> str:
    if c.kind == "pc":
        return PC_ROLES.get(c.char_class or "", "tank")
    if getattr(c, "ai_role", None):
        return c.ai_role
    melee = [a for a in c.attacks if a.type == "melee" and a.id != "unarmed"]
    return "brute" if melee else "archer"


def simple_policy(enc: Encounter, c: Creature) -> dict:
    """Return the next intent for ``c``."""
    menu = enc.legal_actions()
    choice = _emergency(enc, c, menu) or ROLES[role_of(c)](enc, c, menu)
    return choice or {"type": "end_turn"}


# ----------------------------------------------------------------- helpers
def _opts(menu, kind, **match):
    return [o for o in menu if o["intent"]["type"] == kind and all(o["intent"].get(k) == v for k, v in match.items())]


def _first(menu, kind, **match):
    found = _opts(menu, kind, **match)
    return found[0]["intent"] if found else None


def _moves(menu, tag):
    return [o for o in menu if o["intent"]["type"] == "move" and tag in o.get("tags", [])]


def _attacks(enc, c, menu, kind=None):
    out = []
    for o in _opts(menu, "attack"):
        a = c.attack_by_id(o["intent"]["attack"])
        if a.id == "unarmed":
            continue
        if kind and a.type != kind:
            continue
        out.append(o)
    return out


def _target(enc, o):
    it = o["intent"]
    return enc.creatures[it.get("target") or it["targets"][0]]


def _adjacent_enemies(enc, c):
    return [e for e in enc.enemies_of(c) if enc.dist(c, e) <= 5]


def _ally_engaging(enc, c, target):
    return any(enc.dist(al, target) <= 5 and not al.incapacitated for al in enc.allies_of(c))


def _can_act(enc):
    return enc.turn.actions > 0 or enc.turn.attacks_left > 0


def _v2(enc):
    """Tactics 2 (production/features.json "tactics_v2"): goblins use Nimble Escape, shooters close in."""
    return enc.options.get("tactics", 1) >= 2


def _close_in(enc, c, menu, shots):
    """Tactics 2: if the shot we'd take is at long range (disadvantage), step to normal range first,
    as long as the step provokes nobody."""
    if not shots or enc.turn.movement <= 0 or enc.turn.disengaged:
        return None
    pick = max(shots, key=lambda o: _score_target(enc, c, o))
    if "-long range" not in pick.get("notes", []):
        return None
    moves = [o for o in _moves(menu, "close_range") if not o["provokes"]]
    same = [o for o in moves if o.get("target") == pick["intent"]["target"]]
    choice = same or moves
    return choice[0]["intent"] if choice else None


def _nimble(enc, c, menu):
    """Tactics 2, for creatures with Nimble Escape (goblins): slip past a well-armoured defender to
    reach a softer target (AC 3+ lower), and, once bloodied, hit, Disengage out of reach (once a
    fight) and keep shooting from there."""
    adjacent = _adjacent_enemies(enc, c)
    ts = enc.turn
    memo = enc.ai_memo.setdefault(c.id, {})
    bloodied = c.hp <= c.max_hp // 2
    if ts.disengaged and ts.movement > 0 and _can_act(enc):
        here = min((e.ac for e in adjacent), default=99)
        soft = [o for o in _moves(menu, "engage") if _engage_target(enc, o) and _engage_target(enc, o).ac <= here - 3]
        if soft:
            return min(soft, key=lambda o: (_engage_target(enc, o).ac, int(o["cost"].split()[0])))["intent"]
        return None
    if ts.disengaged and ts.movement > 0 and not _can_act(enc) and adjacent and bloodied and not memo.get("ran"):
        memo["ran"] = True                                  # once a fight: no endless chase around the map
        return _retreat_if_threatened(enc, c, menu, safe_only=False)
    if bloodied and not adjacent and _can_act(enc):
        # Hurt and out of reach: keep the distance and shoot rather than walk back in.
        shots = [o for o in _attacks(enc, c, menu, "ranged") if not any(n.startswith("-hostile") for n in o.get("notes", []))]
        if shots:
            return _close_in(enc, c, menu, shots) or _best(enc, c, shots)
        return None
    if not adjacent or not ts.bonus_action or ts.movement <= 0:
        return None
    if _can_act(enc):
        here = min(e.ac for e in adjacent)
        soft = [o for o in _moves(menu, "engage") if o["provokes"] and _engage_target(enc, o)
                and _engage_target(enc, o).ac <= here - 3]
        if soft:
            return _first(menu, "disengage", bonus=True)
        return None
    if bloodied and not memo.get("ran") and any(a.type == "ranged" for a in c.attacks):
        return _first(menu, "disengage", bonus=True)       # hit, then slip out of reach to shoot
    return None


def _engage_target(enc, o):
    return enc.creatures.get(o.get("target", ""))


def _score_target(enc, c, o, prefer_squishy=True):
    t = _target(enc, o)
    s = o.get("hit_chance", 0.6)
    if t.hp <= 6:
        s *= 1.8  # finish it
    if prefer_squishy and t.kind == "pc" and t.ac <= 14:
        s *= 1.3
    return (s, -t.hp, t.id)


def _best(enc, c, options, **kw):
    if not options:
        return None
    return max(options, key=lambda o: _score_target(enc, c, o, **kw))["intent"]


def _emergency(enc: Encounter, c: Creature, menu):
    # Get up first: prone means disadvantage on your own attacks.
    if c.has_condition("prone"):
        it = _first(menu, "stand_up")
        if it:
            return it
    if c.kind != "pc":
        return None
    down = [a for a in enc.allies_of(c, standing_only=False) if a.hp == 0 and not a.dead]
    for a in down:
        for spell in ("healing_word", "cure_wounds"):
            it = _first(menu, "cast", spell=spell, targets=[a.id])
            if it:
                return it
    if c.hp <= c.max_hp // 2:
        it = _first(menu, "second_wind")
        if it:
            return it
    if c.hp <= c.max_hp // 3:
        it = _first(menu, "use_item", item="potion_of_healing")
        if it:
            return it
    return None


def _retreat_if_threatened(enc, c, menu, safe_only=True):
    if not _adjacent_enemies(enc, c) and not any(enc.dist(c, e) <= 10 for e in enc.enemies_of(c)):
        return None
    for o in _moves(menu, "retreat"):
        if not safe_only or not o["provokes"]:
            return o["intent"]
    return None


# ------------------------------------------------------------------- roles
def tank(enc, c, menu):
    if _can_act(enc):
        melee = _attacks(enc, c, menu, "melee")
        if melee:
            # Prefer whoever is threatening a squishy ally.
            def threat(o):
                t = _target(enc, o)
                menace = any(enc.dist(t, al) <= 5 and al.ac <= 14 for al in enc.allies_of(c))
                return (menace, *_score_target(enc, c, o))
            return max(melee, key=threat)["intent"]
        if enc.turn.attacks_left == 0 and enc.turn.movement > 0:
            guard = sorted(_moves(menu, "guard"), key=lambda o: (len(o["provokes"]), int(o["cost"].split()[0])))
            if guard:
                return guard[0]["intent"]
            engage = sorted(_moves(menu, "engage"), key=lambda o: (len(o["provokes"]), int(o["cost"].split()[0])))
            if engage:
                return engage[0]["intent"]
            adv = _moves(menu, "advance")
            if adv:
                return adv[0]["intent"]
        ranged = _attacks(enc, c, menu, "ranged")
        if ranged:
            return _best(enc, c, ranged)
    return None


def skirmisher(enc, c, menu):
    if c.sneak_attack_dice and "cunning_action" in c.features and not _can_act(enc) and enc.turn.bonus_action:
        if _adjacent_enemies(enc, c):
            it = _first(menu, "disengage", bonus=True)
            if it:
                return it
    if _can_act(enc):
        adjacent = _adjacent_enemies(enc, c)
        ranged = [o for o in _attacks(enc, c, menu, "ranged") if ":thrown" not in o["intent"]["attack"]]
        melee = _attacks(enc, c, menu, "melee")
        sneak_melee = [o for o in melee if _ally_engaging(enc, c, _target(enc, o)) or "+flanking" in o.get("notes", [])
                       or "had_advantage" in o.get("notes", [])]
        if adjacent:
            if sneak_melee:
                return _best(enc, c, sneak_melee, prefer_squishy=False)
            if melee:
                return _best(enc, c, melee, prefer_squishy=False)
        if enc.options.get("flanking") and enc.turn.attacks_left == 0:
            flank = [o for o in _moves(menu, "flank") if not o["provokes"]]
            if flank:
                return flank[0]["intent"]
        sneak_ranged = [o for o in ranged if _ally_engaging(enc, c, _target(enc, o))
                        and not any(n.startswith("-") for n in o.get("notes", []))]
        if sneak_ranged:
            return _best(enc, c, sneak_ranged, prefer_squishy=False)
        if ranged:
            return _best(enc, c, ranged, prefer_squishy=False)
        if enc.turn.attacks_left == 0 and enc.turn.movement > 0:
            for tag in ("engage", "advance"):
                opts = [o for o in _moves(menu, tag) if not o["provokes"]]
                if opts:
                    return opts[0]["intent"]
    if enc.turn.movement > 0 and not _can_act(enc):
        return _retreat_if_threatened(enc, c, menu)
    return None


def artillery(enc, c, menu):
    if enc.turn.actions > 0:
        adjacent = _adjacent_enemies(enc, c)
        if adjacent:
            sg = [o for o in _opts(menu, "cast", spell="shocking_grasp")]
            if sg:
                return _best(enc, c, sg, prefer_squishy=False)
        if enc.turn.movement > 0 and any(enc.dist(c, e) <= 10 for e in enc.enemies_of(c)):
            it = _retreat_if_threatened(enc, c, menu)
            if it:
                return it
        areas = [o for o in menu if o["intent"]["type"] == "cast" and o.get("enemies_hit") is not None
                 and len(o["enemies_hit"]) >= 2 and not o["allies_hit"]]
        if areas:
            return max(areas, key=lambda o: (len(o["enemies_hit"]), o["label"]))["intent"]
        mm = _opts(menu, "cast", spell="magic_missile")
        finish = [o for o in mm if _target(enc, o).hp <= 5]
        if finish:
            return finish[0]["intent"]
        bolts = [o for o in _opts(menu, "cast") if o["intent"]["spell"] in ("fire_bolt", "ray_of_frost")]
        if bolts:
            return _best(enc, c, bolts, prefer_squishy=False)
        if enc.turn.movement > 0:
            adv = _moves(menu, "advance")
            if adv and not adv[0]["provokes"]:
                return adv[0]["intent"]
    if enc.turn.movement > 0:
        return _retreat_if_threatened(enc, c, menu)
    return None


def support(enc, c, menu):
    allies = enc.allies_of(c, include_self=True)
    if enc.turn.bonus_action:
        low = [a for a in allies if a.hp <= a.max_hp // 3 and a.hp < a.max_hp]
        for a in sorted(low, key=lambda a: a.hp):
            it = _first(menu, "cast", spell="healing_word", targets=[a.id])
            if it:
                return it
    if enc.turn.actions > 0:
        if not c.concentration and enc.round <= 2:
            bless = [o for o in _opts(menu, "cast", spell="bless") if len(o["intent"]["targets"]) >= 2]
            if bless:
                return bless[0]["intent"]
        if _adjacent_enemies(enc, c) and enc.turn.movement > 0:
            it = _retreat_if_threatened(enc, c, menu)
            if it:
                return it
        flame = _opts(menu, "cast", spell="sacred_flame")
        if flame:
            return _best(enc, c, flame, prefer_squishy=False)
        melee = _attacks(enc, c, menu, "melee")
        if melee:
            return _best(enc, c, melee, prefer_squishy=False)
        if enc.turn.movement > 0:
            adv = [o for o in _moves(menu, "advance") if not o["provokes"]]
            if adv:
                return adv[0]["intent"]
    return None


def brute(enc, c, menu):
    if _v2(enc) and "nimble_escape" in c.traits:
        it = _nimble(enc, c, menu)
        if it:
            return it
    if _can_act(enc):
        melee = _attacks(enc, c, menu, "melee")
        if melee:
            return _best(enc, c, melee)
        if enc.turn.attacks_left == 0 and enc.turn.movement > 0:
            engage = _moves(menu, "engage")
            if engage:
                def softness(o):
                    tid = o["label"].split("(")[1].split(")")[0]
                    t = enc.creatures.get(tid)
                    return ((t.ac if t else 20), len(o["provokes"]), int(o["cost"].split()[0]))
                return min(engage, key=softness)["intent"]
            adv = _moves(menu, "advance")
            if adv:
                return adv[0]["intent"]
        ranged = _attacks(enc, c, menu, "ranged")
        if ranged:
            if _v2(enc):
                it = _close_in(enc, c, menu, ranged)
                if it:
                    return it
            return _best(enc, c, ranged)
    return None


def archer(enc, c, menu):
    if _adjacent_enemies(enc, c) and enc.turn.bonus_action and enc.turn.movement > 0:
        it = _first(menu, "disengage", bonus=True)
        if it:
            return it
    if enc.turn.disengaged and enc.turn.movement > 0 and _adjacent_enemies(enc, c):
        it = _retreat_if_threatened(enc, c, menu, safe_only=False)
        if it:
            return it
    if _can_act(enc):
        ranged = [o for o in _attacks(enc, c, menu, "ranged") if not any(n.startswith("-hostile") for n in o.get("notes", []))]
        if ranged:
            if _v2(enc):
                it = _close_in(enc, c, menu, ranged)
                if it:
                    return it
            return _best(enc, c, ranged)
        melee = _attacks(enc, c, menu, "melee")
        if melee:
            return _best(enc, c, melee)
        any_ranged = _attacks(enc, c, menu, "ranged")
        if any_ranged:
            return _best(enc, c, any_ranged)
        if enc.turn.attacks_left == 0 and enc.turn.movement > 0:
            adv = _moves(menu, "advance")
            if adv:
                return adv[0]["intent"]
    return None


ROLES = {"tank": tank, "skirmisher": skirmisher, "artillery": artillery, "support": support,
         "brute": brute, "archer": archer}
