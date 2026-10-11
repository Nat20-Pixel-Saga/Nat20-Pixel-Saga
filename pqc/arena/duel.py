"""Arena duels: two creatures, best of N bouts, every roll from the seeded engine.

``run_match`` plays the bouts and, after every action, estimates each side's
chance of winning the match by replaying the rest of the fight many times from
that exact state with fresh dice (the live "win chance" bar). The estimate is
commentary only: it never touches the real fight's dice.
"""
from __future__ import annotations

import copy
import hashlib
import os
import pickle
from concurrent.futures import ProcessPoolExecutor

from ..ai import simple_policy
from ..combat import Encounter, EngineError
from ..dice import Dice
from ..state import monster_from_data


def duel_policy(enc: Encounter, c):
    """The stock policy, plus the composition of a Multiattack: the engine
    counts the attacks but does not say which ones, so take them in the listed order."""
    intent = simple_policy(enc, c)
    if intent and intent.get("type") == "attack" and c.multiattack:
        left = enc.turn.attacks_left
        i = (len(c.multiattack) - left) if left > 0 else 0
        intent = {**intent, "attack": c.multiattack[i % len(c.multiattack)]}
    return intent


def build(a: dict, b: dict, seed: str, blocked=None, name: str = "Arena duel") -> Encounter:
    """``a`` / ``b``: {"id", "monster", "name", "pos"}. ``a`` is team "party", ``b`` team "enemies"."""
    ca = monster_from_data(a["monster"], a["id"], team="party", pos=tuple(a["pos"]), name=a["name"])
    cb = monster_from_data(b["monster"], b["id"], team="enemies", pos=tuple(b["pos"]), name=b["name"])
    return Encounter([ca, cb], Dice(seed), name=name, occupied_extra=set(blocked or ()))


def _advance(enc: Encounter, on_act=None, max_rounds: int = 30) -> None:
    """Encounter.run with a hook after every action (same order of policy calls, so same dice)."""
    if not enc.started:
        enc.start()
        if on_act:
            on_act(enc)
    while not enc.finished and enc.round <= max_rounds:
        c = enc.current
        steps = 0
        while enc.can_act(c) and not enc.finished and steps < 20:
            steps += 1
            intent = duel_policy(enc, c)
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


def _fresh_wins(args) -> int:
    a, b, blocked, tag, lo, hi = args
    wins = 0
    for i in range(lo, hi):
        enc = build(a, b, f"{tag}-{i}", blocked)
        _advance(enc)
        wins += enc.result()["winner"] == "party"
    return wins


def _replay_wins(args) -> int:
    blob, seed, seq, lo, hi = args
    wins = 0
    for k in range(lo, hi):
        c = pickle.loads(blob)
        c.dice = Dice("mc-" + hashlib.sha256(f"{seed}|{seq}|{k}".encode()).hexdigest()[:16])
        _advance(c)
        wins += c.result()["winner"] == "party"
    return wins


def _spread(fn, jobs: list) -> int:
    """Sum ``fn`` over ``jobs`` on every core. Each job's dice depend only on its own indices,
    so the total is the same however the work is split."""
    workers = max(1, os.cpu_count() or 1)
    if workers == 1 or len(jobs) == 1:
        return sum(fn(j) for j in jobs)
    with ProcessPoolExecutor(workers) as ex:
        return sum(ex.map(fn, jobs))


def _chunks(n: int, size: int = 250) -> list[tuple[int, int]]:
    return [(lo, min(n, lo + size)) for lo in range(0, n, size)]


def bout_odds(a: dict, b: dict, n: int, blocked=None, tag: str = "odds") -> float:
    """Chance that ``a`` wins a fresh bout, from ``n`` independent fights."""
    return _spread(_fresh_wins, [(a, b, blocked, tag, lo, hi) for lo, hi in _chunks(n)]) / n


def match_chance(p_now: float, p_fresh: float, score: tuple[int, int], need: int) -> float:
    """Chance ``a`` wins the match given the current bout's chance and the score."""
    def m(x, y):
        if x >= need:
            return 1.0
        if y >= need:
            return 0.0
        return p_fresh * m(x + 1, y) + (1 - p_fresh) * m(x, y + 1)
    return p_now * m(score[0] + 1, score[1]) + (1 - p_now) * m(score[0], score[1] + 1)


def run_bout(a: dict, b: dict, seed: str, blocked=None, samples: int = 300) -> dict:
    """One real bout. Returns the engine result plus ``odds``: {event seq -> chance ``a`` wins this bout}
    measured after each action."""
    enc = build(a, b, seed, blocked)
    snaps: list[tuple[int, Encounter]] = []

    def snap(e: Encounter):
        snaps.append((e.events[-1]["seq"], copy.deepcopy(e)))

    _advance(enc, on_act=snap)
    result = enc.result()
    odds: dict[int, float] = {}
    open_snaps = []
    for seq, s in snaps:
        if s.finished:
            odds[seq] = 1.0 if s.result()["winner"] == "party" else 0.0
        else:
            open_snaps.append((seq, pickle.dumps(s)))
    half = max(1, samples // 2)
    jobs = [(blob, seed, seq, lo, min(samples, lo + half)) for seq, blob in open_snaps for lo in range(0, samples, half)]
    workers = max(1, os.cpu_count() or 1)
    if workers > 1 and jobs:
        with ProcessPoolExecutor(workers) as ex:
            wins = list(ex.map(_replay_wins, jobs))
    else:
        wins = [_replay_wins(j) for j in jobs]
    for (blob, _, seq, lo, hi), w in zip(jobs, wins):
        odds[seq] = odds.get(seq, 0.0) + w / samples
    result["odds"] = odds
    result["attack_types"] = {(c.id, at.id): at.type for c in enc.creatures.values() for at in c.attacks}
    return result


def run_match(a: dict, b: dict, seed: str, best_of: int = 3, blocked=None, samples: int = 300,
              prior_n: int = 2000) -> dict:
    need = best_of // 2 + 1
    p_fresh = bout_odds(a, b, prior_n, blocked, tag=f"{seed}-prior")
    score = [0, 0]
    bouts = []
    while max(score) < need:
        n = len(bouts) + 1
        r = run_bout(a, b, f"{seed}-bout{n}", blocked, samples)
        r["score_before"] = tuple(score)
        r["match_odds"] = {s: match_chance(p, p_fresh, tuple(score), need) for s, p in r["odds"].items()}
        r["match_odds_start"] = match_chance(p_fresh, p_fresh, tuple(score), need)
        score[0 if r["winner"] == "party" else 1] += 1
        r["score_after"] = tuple(score)
        bouts.append(r)
    return {"seed": seed, "best_of": best_of, "p_fresh": p_fresh, "prior_n": prior_n, "samples": samples,
            "bouts": bouts, "score": tuple(score), "winner": a["id"] if score[0] > score[1] else b["id"]}
