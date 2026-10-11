"""Arena formats on top of the rules engine: bouts between any number of sides,
with a live win chance after every action.

A *fighter* is a dict: ``{"id", "monster", "name", "team", "pos"}`` (plus
``sprite`` for the renderer). Fighters on the same ``team`` are allies; give
every fighter its own team for a free-for-all.

The win chance is commentary only. After each action that changes the state of
the fight, the rest of the fight is replayed ``samples`` times from that exact
state with dice derived from a separate seed, and each team's share of the wins
is recorded. The real fight's dice are never touched, and the whole computation
is deterministic: the same seed always gives the same video.
"""
from __future__ import annotations

import copy
import hashlib
import os
import pickle
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from .. import data
from ..ai import simple_policy
from ..combat import Encounter, EngineError
from ..dice import Dice
from ..rules import size_index
from ..state import monster_from_data

MAX_ROUNDS = 30


# ------------------------------------------------------------------ fights
def _used_this_action(enc: Encounter, c) -> list[str]:
    """Attack ids already made with the current Multiattack (since the turn started)."""
    if enc.turn.attacks_left <= 0:
        return []
    used = []
    for e in reversed(enc.events):
        if e["t"] == "turn_start":
            break
        if e["t"] == "attack" and e.get("actor") == c.id and not e.get("opportunity"):
            used.append(e["attack"].split(":")[0])
    n_done = len(c.multiattack) - enc.turn.attacks_left
    return used[:n_done][::-1]


def policy(enc: Encounter, c):
    """The stock policy, plus the composition of a fixed Multiattack ("one Bite and one Claw"):
    the engine counts the attacks but does not say which ones, so each attack is one still owed
    (the stock choice when it is, otherwise one that reaches). Multiattacks "in any combination"
    are left to the stock policy. A Tail that "can't target" the creature this monster is
    grappling swings at someone else in reach, or is skipped."""
    intent = simple_policy(enc, c)
    if not (intent and intent.get("type") == "attack" and c.multiattack and not getattr(c, "multiattack_any", False)):
        return intent
    remaining = list(c.multiattack)
    for u in _used_this_action(enc, c):
        if u in remaining:
            remaining.remove(u)
    if not remaining:
        remaining = list(c.multiattack)
    tgt = enc.creatures.get(intent["target"])
    held = lambda t: (t.conditions.get("grappled") or {}).get("source") == c.id  # noqa: E731
    not_vs_held = set(getattr(c, "not_vs_held", ()))

    def ok(aid, t):
        a = c.attack_by_id(aid)
        return a is not None and t is not None and enc.dist(c, t) <= a.reach_ft and not (aid in not_vs_held and held(t))

    want = intent["attack"].split(":")[0]
    order = ([want] if want in remaining else []) + [a for a in remaining if a != want]
    # Knock it down first: an owed attack that leaves the target Prone gives the rest Advantage.
    if tgt is not None and not tgt.has_condition("prone"):
        def topples(aid):
            oh = (c.attack_by_id(aid).on_hit or {}) if c.attack_by_id(aid) else {}
            return oh.get("condition") == "prone" and size_index(tgt.size) <= size_index(oh.get("max_size", "huge"))
        order = [a for a in order if topples(a)] + [a for a in order if not topples(a)]
    for aid in order:
        if ok(aid, tgt):
            return {**intent, "attack": aid}
    # Nothing owed reaches the chosen target: another enemy in reach for the next owed attack.
    for aid in order:
        a = c.attack_by_id(aid)
        others = [e for e in enc.enemies_of(c) if ok(aid, e)]
        if a and others:
            return {**intent, "attack": aid, "target": min(others, key=lambda e: (e.hp, e.id)).id}
    return {"type": "end_turn"}


def make_encounter(fighters: list[dict], seed: str, blocked=None, name: str = "Arena") -> Encounter:
    mons = data.monsters()
    cs = []
    for f in fighters:
        c = monster_from_data(f["monster"], f["id"], team=f["team"], pos=tuple(f["pos"]), name=f["name"])
        c.multiattack_any = bool(mons[f["monster"]].get("multiattack_any"))
        c.not_vs_held = tuple(x["id"] for x in mons[f["monster"]]["attacks"] if x.get("not_vs_held"))
        cs.append(c)
    return Encounter(cs, Dice(seed), name=name, occupied_extra=set(blocked or ()))


def advance(enc: Encounter, on_act=None, max_rounds: int = MAX_ROUNDS) -> None:
    """Encounter.run, with a hook after every action. Same order of policy calls as run(), so same dice."""
    if not enc.started:
        enc.start()
        if on_act:
            on_act(enc)
    while not enc.finished and enc.round <= max_rounds:
        c = enc.current
        steps = 0
        while enc.can_act(c) and not enc.finished and steps < 20:
            steps += 1
            intent = policy(enc, c)
            if not intent or intent.get("type") == "end_turn":
                break
            try:
                enc.act(intent)
            except EngineError as exc:
                enc.emit("illegal_intent", actor=c.id, intent=intent, reason=str(exc))
                break
            if on_act:
                on_act(enc)
        if not enc.finished:
            enc.end_turn()
    if not enc.finished:
        enc.emit("encounter_timeout", rounds=enc.round)


def winner(enc: Encounter) -> str | None:
    r = enc.result()
    return r["winner"] if r["finished"] else None


def _signature(enc: Encounter) -> tuple:
    return tuple((c.id, c.hp, c.temp_hp, repr(c.conditions), c.dead) for c in enc.creatures.values())


# ------------------------------------------------------------- Monte Carlo
def _workers() -> int:
    return max(1, os.cpu_count() or 1)


def _fresh_wins(args) -> Counter:
    fighters, blocked, tag, lo, hi = args
    out: Counter = Counter()
    for i in range(lo, hi):
        enc = make_encounter(fighters, f"{tag}-{i}", blocked)
        advance(enc)
        out[winner(enc)] += 1
    return out


def _replay_wins(args) -> Counter:
    blob, tag, lo, hi = args
    out: Counter = Counter()
    for k in range(lo, hi):
        c = pickle.loads(blob)
        c.dice = Dice("mc-" + hashlib.sha256(f"{tag}|{k}".encode()).hexdigest()[:16])
        advance(c)
        out[winner(c)] += 1
    return out


def _pool_map(fn, jobs: list) -> list:
    if _workers() == 1 or len(jobs) <= 1:
        return [fn(j) for j in jobs]
    with ProcessPoolExecutor(_workers()) as ex:
        return list(ex.map(fn, jobs))


def _shares(c: Counter, teams: list[str]) -> dict[str, float]:
    n = sum(v for k, v in c.items() if k in teams) or 1
    return {t: c.get(t, 0) / n for t in teams}


def fresh_odds(fighters: list[dict], n: int, blocked=None, tag: str = "odds") -> dict[str, float]:
    """Each team's chance to win a fresh bout, from ``n`` independent fights (timeouts ignored)."""
    teams = sorted({f["team"] for f in fighters})
    size = max(25, n // (_workers() * 4))
    jobs = [(fighters, blocked, tag, lo, min(n, lo + size)) for lo in range(0, n, size)]
    total: Counter = Counter()
    for c in _pool_map(_fresh_wins, jobs):
        total.update(c)
    return _shares(total, teams)


def run_bout(fighters: list[dict], seed: str, blocked=None, samples: int = 300) -> dict:
    """One real bout. ``odds`` maps event seq -> {team: chance to win this bout}, measured after
    every action that changed hit points or conditions (and at the start)."""
    teams = sorted({f["team"] for f in fighters})
    enc = make_encounter(fighters, seed, blocked)
    snaps: list[tuple[int, bytes | None, dict | None]] = []
    last = {"sig": None}

    def snap(e: Encounter):
        sig = _signature(e)
        if sig == last["sig"] and snaps:
            return
        last["sig"] = sig
        seq = e.events[-1]["seq"]
        if e.finished:
            w = winner(e)
            snaps.append((seq, None, {t: 1.0 if t == w else 0.0 for t in teams}))
        else:
            snaps.append((seq, pickle.dumps(e), None))

    advance(enc, on_act=snap)
    result = enc.result()
    if not result["finished"]:
        raise RuntimeError(f"bout {seed} timed out")
    jobs, owners = [], []
    half = max(1, samples // 2)
    for i, (seq, blob, fixed) in enumerate(snaps):
        if blob is None:
            continue
        for lo in range(0, samples, half):
            jobs.append((blob, f"{seed}|{seq}", lo, min(samples, lo + half)))
            owners.append(i)
    counts: dict[int, Counter] = {}
    for i, c in zip(owners, _pool_map(_replay_wins, jobs)):
        counts.setdefault(i, Counter()).update(c)
    odds = {}
    for i, (seq, blob, fixed) in enumerate(snaps):
        odds[seq] = fixed if fixed is not None else _shares(counts[i], teams)
    result["odds"] = odds
    result["teams"] = teams
    result["attack_types"] = {(c.id, at.id): at.type for c in enc.creatures.values() for at in c.attacks}
    result["fighters"] = copy.deepcopy(fighters)
    return result


def odds_at(bout: dict, seq: int) -> dict[str, float]:
    """The win chance as it stood right after event ``seq``."""
    keys = sorted(bout["odds"])
    best = keys[0]
    for k in keys:
        if k <= seq:
            best = k
        else:
            break
    return bout["odds"][best]


# ------------------------------------------------------------ best of N
def match_chance(p_now: float, p_fresh: float, score: tuple[int, int], need: int) -> float:
    """Chance side A wins a first-to-``need`` match, given its chance in the current bout."""
    def m(x, y):
        if x >= need:
            return 1.0
        if y >= need:
            return 0.0
        return p_fresh * m(x + 1, y) + (1 - p_fresh) * m(x, y + 1)
    return p_now * m(score[0] + 1, score[1]) + (1 - p_now) * m(score[0], score[1] + 1)


def best_of(fighters_a: list[dict], fighters_b: list[dict], seed: str, n: int, blocked=None,
            samples: int = 300, prior_n: int = 3000) -> dict:
    """A best-of-``n`` match between side "a" and side "b" (fresh fighters every bout)."""
    fs = [{**f, "team": "a"} for f in fighters_a] + [{**f, "team": "b"} for f in fighters_b]
    need = n // 2 + 1
    p_fresh = fresh_odds(fs, prior_n, blocked, tag=f"{seed}-prior")["a"]
    score = [0, 0]
    bouts = []
    while max(score) < need:
        k = len(bouts) + 1
        r = run_bout(fs, f"{seed}-bout{k}", blocked, samples)
        r["score_before"] = tuple(score)
        r["match_odds"] = {s: match_chance(o["a"], p_fresh, tuple(score), need) for s, o in r["odds"].items()}
        r["match_odds_start"] = match_chance(p_fresh, p_fresh, tuple(score), need)
        score[0 if r["winner"] == "a" else 1] += 1
        r["score_after"] = tuple(score)
        bouts.append(r)
    return {"kind": "best_of", "seed": seed, "best_of": n, "need": need, "p_fresh": p_fresh, "prior_n": prior_n,
            "p_match": match_chance(p_fresh, p_fresh, (0, 0), need), "bouts": bouts, "score": tuple(score),
            "winner": "a" if score[0] > score[1] else "b"}


def tournament_odds(entrants: list[str], p: dict[tuple[str, str], float], bracket_need: list[int]) -> dict[str, float]:
    """Chance each entrant wins a single-elimination bracket (entrants in bracket order), where
    p[(x, y)] is x's chance to win one bout against y and round r is first to bracket_need[r]."""
    def match(x, y, need):
        q = p[(x, y)]
        return match_chance(q, q, (0, 0), need)

    dist = [{e: 1.0} for e in entrants]
    r = 0
    while len(dist) > 1:
        nxt = []
        for i in range(0, len(dist), 2):
            left, right = dist[i], dist[i + 1]
            out: dict[str, float] = {}
            for x, px in left.items():
                for y, py in right.items():
                    w = match(x, y, bracket_need[r])
                    out[x] = out.get(x, 0) + px * py * w
                    out[y] = out.get(y, 0) + px * py * (1 - w)
            nxt.append(out)
        dist = nxt
        r += 1
    return dist[0]
