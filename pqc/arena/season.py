"""The Pit, a season: episode specs -> simulated results -> timelines.

``production/arena/s1.json`` lists the episodes. Every fight's seed is written
there before anything is simulated, and later episodes take their line-ups from
earlier results (the Last Chance Rumble gets the qualifiers' losers, the Crown
gets the winners), so a season is one deterministic chain.

Results are cached as JSON next to the renders (``result.json``), so the
episode, its Shorts and its thumbnail all read the same simulation.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import data
from ..dice import Dice
from ..render.assets import Assets
from ..render.tilemap import TileMap
from . import formats
from . import show as S

ROOT = Path(__file__).resolve().parents[2]
MAP = "arena_pit"
DUEL_POS = {"a": (6, 7), "b": (14, 8)}
HORDE_POS = [(14, 7), (14, 8), (15, 6), (15, 9), (13, 6), (13, 9), (16, 7), (16, 8), (15, 5), (15, 10), (16, 5),
             (16, 10), (12, 7), (12, 8), (13, 5), (13, 10)]
RING_POS = [(5, 5), (15, 10), (10, 5), (10, 10), (15, 5), (5, 10), (4, 7), (16, 8)]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


# ================================================================== season
def load(path: str | Path) -> dict:
    s = json.loads(Path(path).read_text())
    s["_path"] = str(path)
    return s


def episode(season: dict, n: int) -> dict:
    return next(e for e in season["episodes"] if e["n"] == n)


def nice_date(iso: str) -> str:
    import datetime as dt
    d = dt.date.fromisoformat(iso)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def short_date(iso: str) -> str:
    import datetime as dt
    d = dt.date.fromisoformat(iso)
    return f"{DAYS[d.weekday()][:3]} {d.day} {MONTHS[d.month - 1]}"


class Arena:
    """The pit's geometry: blocked squares and the crowd."""

    def __init__(self, assets: Assets):
        self.assets = assets
        tm = TileMap.load(MAP, assets)
        self.tm = tm
        self.crowd = sorted((k for k in tm.points if k.startswith("crowd_")), key=lambda k: int(k.split("_")[1]))
        self.facing = json.loads((ROOT / "assets" / "maps" / f"{MAP}.json").read_text())["crowd_facing"]
        self.blocked = set(tm.blocked(assets)) | {tuple(tm.points[k]) for k in self.crowd}
        self.center = tm.points["center"]


# ============================================================== simulation
def fighter(mid: str, fid: str, team: str, pos, name: str | None = None, sprite: str | None = None) -> dict:
    return {"id": fid, "monster": mid, "name": name or data.monsters()[mid]["name"], "team": team, "pos": list(pos),
            "sprite": sprite or mid}


def _ser_bout(b: dict) -> dict:
    out = {k: v for k, v in b.items() if k not in ("odds", "attack_types", "match_odds", "combatants")}
    out["odds"] = {str(k): v for k, v in b.get("odds", {}).items()}
    if "match_odds" in b:
        out["match_odds"] = {str(k): v for k, v in b["match_odds"].items()}
    out["attack_types"] = {f"{c}|{a}": t for (c, a), t in b["attack_types"].items()}
    return out


def _de_bout(b: dict) -> dict:
    b = dict(b)
    b["odds"] = {int(k): v for k, v in b.get("odds", {}).items()}
    if "match_odds" in b:
        b["match_odds"] = {int(k): v for k, v in b["match_odds"].items()}
    b["attack_types"] = {tuple(k.split("|")): v for k, v in b["attack_types"].items()}
    return b


def _bout(fs, seed, arena, samples):
    if samples <= 0:                            # quick: just the real fight (for later episodes' line-ups)
        enc = formats.make_encounter(fs, seed, arena.blocked)
        formats.advance(enc)
        r = enc.result()
        r["odds"], r["teams"] = {}, sorted({f["team"] for f in fs})
        r["attack_types"] = {(c.id, at.id): at.type for c in enc.creatures.values() for at in c.attacks}
        r["fighters"] = fs
        return r
    return formats.run_bout(fs, seed, arena.blocked, samples)


def sim_best_of(a: list[dict], b: list[dict], seed: str, n: int, arena: Arena, samples: int, prior_n: int) -> dict:
    if samples > 0:
        return formats.best_of(a, b, seed, n, arena.blocked, samples, prior_n)
    fs = [{**f, "team": "a"} for f in a] + [{**f, "team": "b"} for f in b]
    need, score, bouts = n // 2 + 1, [0, 0], []
    while max(score) < need:
        r = _bout(fs, f"{seed}-bout{len(bouts) + 1}", arena, 0)
        r["score_before"] = tuple(score)
        score[0 if r["winner"] == "a" else 1] += 1
        r["score_after"] = tuple(score)
        bouts.append(r)
    return {"kind": "best_of", "seed": seed, "best_of": n, "need": need, "p_fresh": 0.5, "p_match": 0.5,
            "prior_n": 0, "bouts": bouts, "score": tuple(score), "winner": "a" if score[0] > score[1] else "b"}


def resolve(season: dict, n: int, arena: Arena, cache_dir: Path, full: bool = True) -> dict:
    """Simulate episode ``n`` (or load it from the cache). ``full`` adds the win-chance replays;
    without it only the real fights are run (enough to know who won)."""
    ep = episode(season, n)
    cache = cache_dir / f"E{n:02d}" / ("result.json" if full else "quick.json")
    if cache.exists():
        return load_result(cache)
    if full:
        quick = cache_dir / f"E{n:02d}" / "quick.json"
        if quick.exists():
            pass
    prev = {k: resolve(season, k, arena, cache_dir, full=False) for k in ep.get("depends", [])}
    q = season["quality"]
    samples = q["samples"] if full else 0
    segs = []
    for si, seg in enumerate(segments(season, ep, prev)):
        kind = seg["kind"]
        seed = seg["seed"]
        if kind == "best_of":
            m = sim_best_of(seg["a"], seg["b"], seed, seg["best_of"], arena,
                            samples if len(seg["a"]) + len(seg["b"]) <= 2 else q["samples_multi"],
                            q["prior"] if full else 0)
            segs.append({**seg, "match": m})
        elif kind == "how_many":
            rounds = []
            ramp = {}
            for k in seg["counts"]:
                fs = [{**seg["star"], "team": "a"}] + [
                    {**fighter(seg["minion"], f"m{i}", "b", HORDE_POS[i], seg["minion_name"], seg.get("minion_sprite")), "team": "b"}
                    for i in range(k)]
                if full:
                    ramp[k] = formats.fresh_odds(fs, q["prior_multi"], arena.blocked, tag=f"{seed}-n{k}")["a"]
            for k in seg["counts"]:
                fs = [{**seg["star"], "team": "a"}] + [
                    {**fighter(seg["minion"], f"m{i}", "b", HORDE_POS[i], seg["minion_name"], seg.get("minion_sprite")), "team": "b"}
                    for i in range(k)]
                r = _bout(fs, f"{seed}-n{k}", arena, q["samples_multi"] if full else 0)
                r["count"] = k
                rounds.append(r)
                if r["winner"] != "a":
                    break
            segs.append({**seg, "ramp": ramp, "rounds": rounds, "prior_n": q["prior_multi"] if full else 0,
                         "answer": rounds[-1]["count"] if rounds[-1]["winner"] != "a" else None})
        elif kind == "rumble":
            fs = seg["fighters"]
            prior = formats.fresh_odds(fs, q["prior_multi"], arena.blocked, tag=f"{seed}-prior") if full else {}
            r = _bout(fs, seed, arena, q["samples_multi"] if full else 0)
            segs.append({**seg, "prior": prior, "bout": r, "prior_n": q["prior_multi"] if full else 0})
    res = {"n": n, "segments": segs, "full": full}
    if full and ep["kind"] in ("crown_semis", "crown_final"):
        qs = qualifiers(season, ep["n"], prev)
        (a0, a1), (b0, b1) = season["crown"]["pairs"]
        order = [qs[i]["monster"] for i in (a0, a1, b0, b1)]
        res["crown_odds"] = crown_odds(order, arena, q["crown_n"], season["crown"]["need"])
    for s in segs:
        for b in bouts_of(s):
            assert Dice.verify_log(b["seed"], b["rolls"]), f"roll log of {b['seed']} does not replay"
    save_result(res, cache)
    return load_result(cache)


def bouts_of(seg: dict) -> list[dict]:
    if seg["kind"] == "best_of":
        return seg["match"]["bouts"]
    if seg["kind"] == "how_many":
        return seg["rounds"]
    return [seg["bout"]]


def save_result(res: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    segs = []
    for s0 in res["segments"]:
        s1 = dict(s0)
        if s0["kind"] == "best_of":
            s1["match"] = {**s0["match"], "bouts": [_ser_bout(b) for b in s0["match"]["bouts"]]}
        elif s0["kind"] == "how_many":
            s1["rounds"] = [_ser_bout(b) for b in s0["rounds"]]
            s1["ramp"] = {str(k): v for k, v in s0["ramp"].items()}
        else:
            s1["bout"] = _ser_bout(s0["bout"])
        segs.append(s1)
    out = {**res, "segments": segs}
    if "crown_odds" in res:
        out["crown_odds"] = res["crown_odds"]
    path.write_text(json.dumps(out, ensure_ascii=False, default=list))


def load_result(path: Path) -> dict:
    res = json.loads(path.read_text())
    for s in res["segments"]:
        if s["kind"] == "best_of":
            s["match"]["bouts"] = [_de_bout(b) for b in s["match"]["bouts"]]
        elif s["kind"] == "how_many":
            s["rounds"] = [_de_bout(b) for b in s["rounds"]]
            s["ramp"] = {int(k): v for k, v in s["ramp"].items()}
        else:
            s["bout"] = _de_bout(s["bout"])
    return res


# ===================================================== who fights in what
def winner_of(seg: dict) -> dict:
    """The fighter (spec) who won a segment."""
    if seg["kind"] == "best_of":
        side = seg["match"]["winner"]
        return seg[side][0]
    if seg["kind"] == "rumble":
        w = seg["bout"]["winner"]
        return next(f for f in seg["fighters"] if f["team"] == w)
    return seg["star"]


def loser_of(seg: dict) -> dict:
    side = "b" if seg["match"]["winner"] == "a" else "a"
    return seg[side][0]


def qualifiers(season: dict, upto: int, results: dict[int, dict]) -> list[dict | None]:
    """The four Crown places in bracket order (None = not decided yet)."""
    out = []
    for slot in season["crown"]["slots"]:
        n = slot["from"]
        if n <= upto and n in results:
            w = winner_of(results[n]["segments"][0])
            out.append({**w, "slot": slot, "episode": n})
        else:
            out.append(None)
    return out


def segments(season: dict, ep: dict, prev: dict[int, dict]) -> list[dict]:
    """The fights of an episode, with fighters placed in the arena."""
    kind, n = ep["kind"], ep["n"]
    if kind == "duel":
        a = fighter(ep["a"], "a1", "a", DUEL_POS["a"])
        b = fighter(ep["b"], "b1", "b", DUEL_POS["b"])
        return [{"kind": "best_of", "seed": ep["seed"], "a": [a], "b": [b], "best_of": ep["best_of"]}]
    if kind == "how_many":
        star = fighter(ep["star"], "star", "a", DUEL_POS["a"], ep.get("star_name"))
        return [{"kind": "how_many", "seed": ep["seed"], "star": star, "minion": ep["minion"],
                 "minion_sprite": ep.get("minion_sprite", ep["minion"]),
                 "minion_name": data.monsters()[ep["minion"]]["name"], "counts": ep["counts"]}]
    if kind == "rumble":
        names = ep.get("names", {})
        roster = [loser_of(prev[k]["segments"][0])["monster"] for k in ep.get("losers_of", [])]
        roster += list(ep.get("fighters", []))
        fs = []
        for i, mid in enumerate(roster):
            nm = names.get(str(i)) or data.monsters()[mid]["name"]
            fs.append(fighter(mid, f"f{i}", f"f{i}", RING_POS[i], nm))
        return [{"kind": "rumble", "seed": ep["seed"], "fighters": fs}]
    if kind == "crown_semis":
        q = qualifiers(season, n, prev)
        out = []
        for k, (i, j) in enumerate(season["crown"]["pairs"]):
            a = fighter(q[i]["monster"], "a1", "a", DUEL_POS["a"])
            b = fighter(q[j]["monster"], "b1", "b", DUEL_POS["b"])
            out.append({"kind": "best_of", "seed": f"{ep['seed']}-sf{k + 1}", "a": [a], "b": [b],
                        "best_of": ep["best_of"], "label": f"SEMIFINAL {k + 1}"})
        return out
    if kind == "crown_final":
        semis = prev[ep["depends"][-1]]["segments"]
        a = fighter(winner_of(semis[0])["monster"], "a1", "a", DUEL_POS["a"])
        b = fighter(winner_of(semis[1])["monster"], "b1", "b", DUEL_POS["b"])
        return [{"kind": "best_of", "seed": ep["seed"], "a": [a], "b": [b], "best_of": ep["best_of"],
                 "label": "THE FINAL"}]
    raise ValueError(kind)


# =================================================================== cues
def _fstatic(f: dict, col, order: int, short: str | None = None) -> dict:
    m = data.monsters()[f["monster"]]
    return {"name": f["name"], "short": short or f["name"], "sprite": f["sprite"], "max_hp": m["hp"], "col": list(col),
            "team": f["team"], "order": order}


def _caption_for(ev, roll, tgt_name, tgt_hp_max, act_name, seen, swing_text=None):
    if ev.get("parried"):
        return ("Parry! The armour turns a hit into a miss.", S.WHITE)
    if ev.get("critical"):
        return ("Natural 20! Damage dice are doubled.", S.GOLD)
    if roll.get("natural") == 1:
        return ("Natural 1: automatic miss.", S.GREY)
    if ev.get("charge") and "charge" not in seen:
        seen.add("charge")
        return ("Charge! 20 feet straight in: extra damage.", S.GOLD)
    if ev.get("hit") and ev["damage"]["hp_after"] <= 0:
        return None
    if ev.get("condition_applied") == "prone" and "prone" not in seen:
        seen.add("prone")
        return ("Knocked prone! Attacks on it roll two d20s.", S.WHITE)
    if swing_text:
        return swing_text
    if ev.get("hit") and 0 < ev["damage"]["hp_after"] <= tgt_hp_max * 0.3 and f"low{ev['target']}" not in seen:
        seen.add(f"low{ev['target']}")
        return (f"{tgt_name} on {ev['damage']['hp_after']} HP. One hit ends it.", S.WHITE)
    if roll.get("advantage") == "advantage" and "adv" not in seen:
        seen.add("adv")
        return ("Advantage: two d20s, keep the best.", S.WHITE)
    if roll.get("advantage") == "disadvantage" and "dis" not in seen:
        seen.add("dis")
        return ("Disadvantage: two d20s, keep the worst.", S.WHITE)
    return None


def fight_cues(bout: dict, names: dict, kinds: dict, odds_fn, swing_fn, tempo: float, music: str | None,
               multi: bool, meta: dict, fstatic: dict) -> list[dict]:
    """Battle cues for one bout, with the show's odds, captions and eliminations."""
    cues = S.battle_cues(bout, kinds=kinds, names=names, attack_types=bout["attack_types"], music=music, origin=(0, 0))
    events = bout["events"]
    rolls = {r["id"]: r for r in bout["rolls"]}
    attacks = [e for e in events if e["t"] == "attack" and not e.get("blocked")]
    by_seq = {e["seq"]: i for i, e in enumerate(events)}
    order = next(e["order"] for e in events if e["t"] == "initiative_order")
    ini = {e["actor"]: e["total"] for e in events if e["t"] == "initiative"}
    killer = {}
    for e in events:
        if e["t"] in ("death", "down") and e["actor"] not in killer:
            for e2 in reversed(events[:by_seq[e["seq"]]]):
                if e2["t"] == "attack" and e2.get("target") == e["actor"] and e2.get("hit"):
                    killer[e["actor"]] = e2["actor"]
                    break
    out, seen, ai = [], set(), 0
    prev = odds_fn(-1)
    standing = {fid for fid in names}
    for cue in cues:
        op = cue["op"]
        if op == "battle_start":
            out.append(cue)
        elif op == "initiative":
            fst = order[0]
            if len(names) == 2:
                a_id, b_id = list(names)
                text = f"Initiative {ini[a_id]} v {ini[b_id]}: {names[fst]} goes first."
            else:
                text = f"Initiative: {names[fst]} goes first ({ini[fst]})."
            out.append({"op": "show_caption", "text": text, "col": fstatic[fst]["col"], "hold": 1.7, "dur": 2.3,
                        "sfx": [[0.0, "dice_roll"], [0.5, "dice_land"]]})
        elif op == "battle_turn":
            out.append({**cue, "op": "show_turn", "hold": 0.3 if not multi else 0.15})
        elif op == "battle_attack":
            ev = attacks[ai]
            ai += 1
            roll = rolls[ev["roll"]]
            now = odds_fn(ev["seq"])
            swing = swing_fn(prev, now)
            cap = _caption_for(ev, roll, names.get(ev["target"], ""), fstatic[ev["target"]]["max_hp"],
                               names.get(ev["actor"], ""), seen, swing)
            # Traits that fired as part of this attack (until the next attack).
            j = by_seq[ev["seq"]] + 1
            while j < len(events) and events[j]["t"] != "attack":
                e2 = events[j]
                if e2["t"] == "trait" and e2.get("trait") == "undead_fortitude" and e2.get("success"):
                    cap = ("Undead Fortitude! It stays up at 1 HP.", S.GOLD)
                if e2["t"] == "trait" and e2.get("trait") == "rampage" and "rampage" not in seen:
                    seen.add("rampage")
                    cap = ("Rampage! A free bite at a bloodied target.", S.GOLD)
                j += 1
            c2 = {**cue, "op": "show_attack", "odds": now, "big": 10, "tempo": tempo,
                  "prone": ev.get("condition_applied") == "prone",
                  "meta": {**meta, "seq": ev["seq"], "swing": swing is not None, "crit": bool(ev.get("critical")),
                           "odds": now}}
            if cap:
                c2["caption"], c2["caption_col"] = cap[0], list(cap[1])
            prev = now
            out.append(c2)
        elif op == "battle_faint":
            out.append(cue)
            fid = cue["actor"]
            standing.discard(fid)
            if multi:
                n_left = len(standing)
                k = killer.get(fid)
                txt = f"{names[fid]} is out! {n_left} left." if not k else \
                    f"{names[k]} drops {names[fid]}! {n_left} left."
                out.append({"op": "show_caption", "text": txt, "col": fstatic[fid]["col"], "hold": 0.0, "dur": 2.0,
                            "sfx": [[0.05, "faint"]]})
        elif op == "battle_end":
            pass
        elif op == "battle_cast":
            out.append(cue)
        else:
            out.append(cue)
    return out


def _swing2(name_a, name_b, col_a, col_b, key="a", thresh=0.15):
    def fn(prev, now):
        p0, p1 = prev.get(key, 0.5), now.get(key, 0.5)
        if abs(p1 - p0) < thresh:
            return None
        lead, col, p = (name_a, col_a, p1) if p1 >= 0.5 else (name_b, col_b, 1 - p1)
        return (f"Big swing: {lead} now {S.pct(p)} to win.", col)
    return fn


def _swing_ffa(fighters_by_team):
    def fn(prev, now):
        if not prev or not now:
            return None
        lead0 = max(prev, key=prev.get)
        lead1 = max(now, key=now.get)
        if lead1 != lead0 and now[lead1] >= 0.2:
            f = fighters_by_team[lead1]
            return (f"New favourite: {f['name']} ({S.pct(now[lead1])}).", tuple(f["col"]))
        return None
    return fn


def crowd_cues(arena: Arena) -> list[dict]:
    out = []
    for i, k in enumerate(arena.crowd):
        out.append({"op": "spawn", "actor": k, "sprite": S.CROWD_SPRITES[(i * 3) % len(S.CROWD_SPRITES)],
                    "at": arena.tm.points[k], "facing": arena.facing[k]})
    return out


def _side(label, sprite, members, col):
    return {"label": label, "sprite": sprite, "members": members, "col": list(col)}


def best_of_cues(seg: dict, music: str, mark: dict, kind_label: str = "BOUT") -> tuple[list[dict], dict]:
    """Tape, odds and every bout of a best-of match. Returns (cues, setup static)."""
    m = seg["match"]
    a, b = seg["a"][0], seg["b"][0]
    fst = {a["id"]: _fstatic(a, S.A_COL, 0), b["id"]: _fstatic(b, S.B_COL, 1)}
    static = {"fmt": "duel", "need": m["need"], "best_of": m["best_of"],
              "sides": {"a": _side(a["name"], a["sprite"], [a["id"]], S.A_COL),
                        "b": _side(b["name"], b["sprite"], [b["id"]], S.B_COL)},
              "fighters_static": fst, "bar_title": "CHANCE TO WIN THE MATCH"}
    names = {a["id"]: a["name"], b["id"]: b["name"]}
    kinds = {a["id"]: a["sprite"], b["id"]: b["sprite"]}
    ma, mb = data.monsters()[a["monster"]], data.monsters()[b["monster"]]
    cues: list[dict] = [{"op": "show_setup", "static": static, "odds": {"a": m["p_match"]}}]
    pre = [
        {"op": "show_card", "kind": "tape", "duration": 5.0, "a": {**a, "col": list(S.A_COL)},
         "b": {**b, "col": list(S.B_COL)}, "rows": S.tape_rows(ma, mb), "sub": seg.get("label", ""),
         "sfx": [[0.0, "transition"]] + [[0.6 + i * 0.45, "dice_land"] for i in range(6)], "meta": {"mark": "tape"}},
        {"op": "show_card", "kind": "odds", "duration": 4.8, "title": f"WE RAN THIS FIGHT {m['prior_n']:,} TIMES",
         "kind_card": "two", "p": m["p_fresh"], "a": {**a, "col": list(S.A_COL)}, "b": {**b, "col": list(S.B_COL)},
         "line": f"Best of {m['best_of']}: {(a if m['p_match'] >= 0.5 else b)['name']} wins "
                 f"{S.pct(max(m['p_match'], 1 - m['p_match']))} of the time.",
         "cta": "Who do you pick? Comment before you watch!", "cta_at": 2.8,
         "sfx": [[0.0, "transition"], [0.5, "dice_roll"], [1.8, "dice_land"], [2.8, "alert"]], "meta": {"mark": "odds"}},
    ]
    cues += pre
    cues.append({"op": "music_stop", "fade_out": 0.3})
    cues.append({"op": "show_reset", "fighters": [a["id"], b["id"]]})
    p_fresh = m["p_fresh"]
    for i, bout in enumerate(m["bouts"]):
        sb = bout["score_before"]
        need = m["need"]
        title = f"{kind_label} {i + 1}"
        if sb[0] == need - 1 and sb[1] == need - 1:
            title = "DECIDER"
        elif max(sb) == need - 1:
            title = f"{kind_label} {i + 1}: MATCH POINT"
        if i:
            cues.append({"op": "fade", "from": "black", "to": "clear", "duration": 0.25, "wait": False})
        chap = title.title().replace("Decider", "Decider") if not seg.get("label") else \
            f"{seg['label'].title()}: {title.title()}"
        cues.append({"op": "show_bout", "title": title, "chapter": chap,
                     "label": f"{seg.get('label', '').strip() + '  ' if seg.get('label') else ''}{kind_label} {i + 1}".strip(),
                     "sub": f"{a['name']}  {sb[0]} - {sb[1]}  {b['name']}", "score": list(sb),
                     "odds": {"a": bout["match_odds_start"]}, "meta": {**mark, "mark": "bout", "bout": i}})
        mo = bout["match_odds"]
        keys = sorted(mo)

        def odds_fn(seq, mo=mo, keys=keys, start=bout["match_odds_start"]):
            if seq < 0:
                return {"a": start}
            best = None
            for k in keys:
                if k <= seq:
                    best = k
            return {"a": mo[best] if best is not None else start}

        fc = fight_cues(bout, names, kinds, odds_fn, _swing2(a["name"], b["name"], S.A_COL, S.B_COL), 1.0,
                        music if i == 0 else None, False, {**mark, "bout": i}, fst)
        # The subscribe prompt rides in after the first initiative of the episode.
        if i == 0 and mark.get("cta"):
            k = next(j for j, c in enumerate(fc) if c["op"] == "show_caption")
            fc.insert(k + 1, {"op": "show_cta", "dur": 4.5, "text": mark["cta"]})
        cues += fc
        sa = bout["score_after"]
        win = a if bout["winner"] == "a" else b
        final = max(sa) >= need
        cues.append({"op": "show_ko", "line": f"{kind_label} {i + 1} GOES TO {win['name'].upper()}",
                     "col": list(S.A_COL if win is a else S.B_COL), "sub": f"{a['name']}  {sa[0]} - {sa[1]}  {b['name']}",
                     "score": list(sa), "odds": {"a": (1.0 if bout["winner"] == "a" else 0.0) if final else
                                                 mo[keys[-1]] if keys else p_fresh},
                     "meta": {**mark, "mark": "ko", "bout": i, "final": final}})
        cues.append({"op": "fade", "to": "black", "duration": 0.25})
        cues.append({"op": "show_reset", "fighters": [a["id"], b["id"]]})
    return cues, static


def match_stats(seg: dict) -> list[list[str]]:
    a, b = seg["a"][0], seg["b"][0]
    s = {a["id"]: {"att": 0, "hit": 0, "crit": 0, "dmg": 0, "max": 0}, b["id"]: {"att": 0, "hit": 0, "crit": 0, "dmg": 0, "max": 0}}
    for bout in seg["match"]["bouts"]:
        for e in bout["events"]:
            if e["t"] == "attack" and not e.get("blocked"):
                r = s[e["actor"]]
                r["att"] += 1
                if e["hit"]:
                    r["hit"] += 1
                    r["crit"] += bool(e["critical"])
                    r["dmg"] += e["damage"]["total"]
                    r["max"] = max(r["max"], e["damage"]["total"])
    x, y = s[a["id"]], s[b["id"]]
    return [["ATTACKS LANDED", f"{x['hit']} of {x['att']}", f"{y['hit']} of {y['att']}"],
            ["CRITICAL HITS", str(x["crit"]), str(y["crit"])],
            ["BIGGEST HIT", str(x["max"]), str(y["max"])],
            ["TOTAL DAMAGE", str(x["dmg"]), str(y["dmg"])]]


def how_many_cues(seg: dict, ep: dict, music: str, mark: dict) -> list[dict]:
    star = seg["star"]
    minion_id = seg["minion"]
    minion = seg.get("minion_sprite", minion_id)
    mm = data.monsters()[minion_id]
    ms = data.monsters()[star["monster"]]
    plural = ep.get("plural", seg["minion_name"] + "s")
    maxk = max(seg["counts"])
    fst = {star["id"]: _fstatic(star, S.A_COL, 0)}
    for i in range(maxk):
        fst[f"m{i}"] = {"name": seg["minion_name"], "short": seg["minion_name"], "sprite": minion, "max_hp": mm["hp"],
                        "col": list(S.B_COL), "team": "b", "order": i + 1}
    static = {"fmt": "horde", "need": 0, "sides": {
        "a": _side(star["name"], star["sprite"], [star["id"]], S.A_COL),
        "b": _side(plural, minion, [], S.B_COL)}, "fighters_static": fst,
        "bar_title": f"CHANCE THE {star['name'].upper()} SURVIVES THIS ROUND"}
    cues: list[dict] = [{"op": "show_setup", "static": static, "odds": {"a": seg["ramp"].get(seg["counts"][0], 0.5)}}]
    cues.append({"op": "show_card", "kind": "tape", "duration": 5.0, "a": {**star, "col": list(S.A_COL)},
                 "b": {"name": seg["minion_name"], "sprite": minion, "col": list(S.B_COL)}, "vs": "VS",
                 "sub": f"ONE {star['name'].upper()}. HOW MANY {plural.upper()}?",
                 "rows": S.tape_rows(ms, mm, count_b="each"), "title": "TALE OF THE TAPE",
                 "minion_id": minion_id,
                 "sfx": [[0.0, "transition"]] + [[0.6 + i * 0.45, "dice_land"] for i in range(6)], "meta": {"mark": "tape"}})
    cues.append({"op": "show_card", "kind": "odds", "kind_card": "ramp", "duration": 6.0,
                 "title": f"WE RAN EVERY ROUND {seg.get('prior_n') or 1000:,} TIMES",
                 "rows": [[f"{k} {plural.upper() if k > 1 else seg['minion_name'].upper()}", seg["ramp"].get(k, 0)]
                          for k in seg["counts"]], "col": list(S.A_COL),
                 "cta": f"How many {plural.lower()} does it take? Comment your number!", "cta_at": 3.4,
                 "sfx": [[0.0, "transition"]] + [[0.4 + i * 0.3, "dice_land"] for i in range(len(seg["counts"]))],
                 "meta": {"mark": "odds"}})
    cues.append({"op": "music_stop", "fade_out": 0.3})
    ids = [star["id"]] + [f"m{i}" for i in range(maxk)]
    cues.append({"op": "show_reset", "fighters": ids})
    for r_i, bout in enumerate(seg["rounds"]):
        k = bout["count"]
        names = {star["id"]: star["name"]}
        kinds = {star["id"]: star["sprite"]}
        for i in range(k):
            names[f"m{i}"] = seg["minion_name"]
            kinds[f"m{i}"] = minion
        if r_i:
            cues.append({"op": "fade", "from": "black", "to": "clear", "duration": 0.25, "wait": False})
        p0 = seg["ramp"].get(k, 0.5)
        cues.append({"op": "show_bout", "title": f"ROUND {r_i + 1}: {k} {plural.upper()}", "label": f"{k} {plural.upper()}",
                     "chapter": f"Round {r_i + 1}: {k} {plural}",
                     "sub": f"The {star['name']} survives this {S.pct(p0)} of the time.", "odds": {"a": p0},
                     "members": [f"m{i}" for i in range(k)], "b_label": f"{k} {plural}",
                     "meta": {**mark, "mark": "bout", "bout": r_i, "count": k}})
        odds = bout["odds"]
        keys = sorted(odds)

        def odds_fn(seq, odds=odds, keys=keys, p0=p0):
            if seq < 0:
                return {"a": p0}
            best = None
            for kk in keys:
                if kk <= seq:
                    best = kk
            return {"a": odds[best]["a"] if best is not None else p0}

        fc = fight_cues(bout, names, kinds, odds_fn, _swing2(star["name"], plural, S.A_COL, S.B_COL, thresh=0.2),
                        0.7, music if r_i == 0 else None, True, {**mark, "bout": r_i}, fst)
        if r_i == 0 and mark.get("cta"):
            j = next(j for j, c in enumerate(fc) if c["op"] == "show_caption")
            fc.insert(j + 1, {"op": "show_cta", "dur": 4.5, "text": mark["cta"]})
        cues += fc
        won = bout["winner"] == "a"
        cues.append({"op": "show_ko", "big": "SURVIVED!" if won else "OVERWHELMED", "big_col": list(S.GOLD if won else S.RED),
                     "line": (f"THE {star['name'].upper()} BEATS {k} {plural.upper()}" if won else
                              f"{k} {plural.upper()} TAKE DOWN THE {star['name'].upper()}"),
                     "col": list(S.A_COL if won else S.B_COL),
                     "sub": "Next round: more of them." if won and r_i + 1 < len(seg["counts"]) else "",
                     "odds": {"a": 1.0 if won else 0.0}, "duration": 2.8,
                     "meta": {**mark, "mark": "ko", "bout": r_i, "final": not won or r_i + 1 == len(seg["rounds"])}})
        cues.append({"op": "fade", "to": "black", "duration": 0.25})
        cues.append({"op": "show_reset", "fighters": ids})
    return cues


def rumble_cues(seg: dict, ep: dict, music: str, mark: dict) -> list[dict]:
    fs = seg["fighters"]
    fst = {}
    for i, f in enumerate(fs):
        fst[f["id"]] = _fstatic(f, S.FFA_COLS[i % len(S.FFA_COLS)], i, short=f["name"])
    by_team = {f["team"]: fst[f["id"]] for f in fs}
    static = {"fmt": "rumble", "need": 0, "sides": {}, "fighters_static": fst,
              "board_title": ep.get("board_title", "LAST ONE STANDING")}
    prior = seg["prior"]
    cues: list[dict] = [{"op": "show_setup", "static": static, "odds": dict(prior)}]
    field = []
    for f in fs:
        m = data.monsters()[f["monster"]]
        field.append({"name": f["name"], "sprite": f["sprite"], "col": fst[f["id"]]["col"], "hp": m["hp"], "ac": m["ac"],
                      "note": m["name"] if f["name"] != m["name"] else S.special(m)})
    cues.append({"op": "show_card", "kind": "field", "duration": 2.4 + 0.35 * len(fs), "fighters": field,
                 "title": ep.get("field_title", "THE FIELD"),
                 "sfx": [[0.0, "transition"]] + [[0.3 + i * 0.35, "dice_land"] for i in range(len(fs))],
                 "meta": {"mark": "tape"}})
    cues.append({"op": "show_card", "kind": "odds", "kind_card": "field", "duration": 5.2,
                 "title": f"WE RAN THIS RUMBLE {seg.get('prior_n') or 1000:,} TIMES",
                 "rows": [[f["name"], prior.get(f["team"], 0), fst[f["id"]]["col"]] for f in fs],
                 "cta": "Who's your pick? Comment before you watch!", "cta_at": 3.2,
                 "sfx": [[0.0, "transition"]] + [[0.3 + i * 0.2, "dice_land"] for i in range(len(fs))],
                 "meta": {"mark": "odds"}})
    cues.append({"op": "music_stop", "fade_out": 0.3})
    ids = [f["id"] for f in fs]
    cues.append({"op": "show_reset", "fighters": ids})
    bout = seg["bout"]
    cues.append({"op": "show_bout", "title": ep.get("bout_title", "THE RUMBLE"), "label": ep.get("label", "RUMBLE"),
                 "chapter": ep.get("bout_title", "THE RUMBLE").title(),
                 "sub": f"{len(fs)} in the pit. One walks out.", "odds": dict(prior),
                 "meta": {**mark, "mark": "bout", "bout": 0}})
    odds = bout["odds"]
    keys = sorted(odds)

    def odds_fn(seq):
        if seq < 0:
            return dict(prior)
        best = None
        for kk in keys:
            if kk <= seq:
                best = kk
        return dict(odds[best]) if best is not None else dict(prior)

    names = {f["id"]: f["name"] for f in fs}
    kinds = {f["id"]: f["sprite"] for f in fs}
    fc = fight_cues(bout, names, kinds, odds_fn, _swing_ffa(by_team), 0.75, music, True, {**mark, "bout": 0}, fst)
    if mark.get("cta"):
        j = next(j for j, c in enumerate(fc) if c["op"] == "show_caption")
        fc.insert(j + 1, {"op": "show_cta", "dur": 4.5, "text": mark["cta"]})
    cues += fc
    w = winner_of(seg)
    cues.append({"op": "show_ko", "big": "LAST ONE STANDING", "big_col": list(S.GOLD),
                 "line": f"{w['name'].upper()} WINS {ep.get('win_what', 'THE RUMBLE')}", "col": fst[w["id"]]["col"],
                 "sub": ep.get("win_sub", ""), "odds": {t: (1.0 if t == w["team"] else 0.0) for t in by_team},
                 "duration": 3.0, "meta": {**mark, "mark": "ko", "bout": 0, "final": True}})
    return cues


def elimination_order(seg: dict) -> list[str]:
    out = []
    for e in seg["bout"]["events"]:
        if e["t"] in ("death", "down") and e["actor"] not in out:
            out.append(e["actor"])
    return out


def road_slots(season: dict, n: int, results: dict[int, dict]) -> list[dict]:
    q = qualifiers(season, n, results)
    slots = []
    for slot, w in zip(season["crown"]["slots"], q):
        if w:
            slots.append({"sprite": w["sprite"], "name": w["name"], "note": slot["note_won"]})
        else:
            slots.append({"name": slot["pending"], "note": slot["note"]})
    return slots


def episode_timeline(season: dict, n: int, results: dict[int, dict], assets: Assets) -> dict:
    """All cues of episode ``n``. ``results`` holds this and every earlier episode's result."""
    ep = episode(season, n)
    res = results[n]
    arena = Arena(assets)
    music = ep.get("music", "battle_boss")
    nxt = next((e for e in season["episodes"] if e["n"] == n + 1 and not e.get("bonus")), None)
    cta = ep.get("cta", "CALL YOUR WINNER  +  SUBSCRIBE")
    cues: list[dict] = [
        {"op": "scene", "map": MAP, "time_of_day": ep.get("time_of_day", "day"), "camera": arena.center},
        {"op": "fade", "from": "black", "to": "clear", "duration": 0.35, "wait": False},
    ]
    cues += crowd_cues(arena)
    seg0 = res["segments"][0]
    first_static = None
    # Hook.
    hook = ep["hook"]
    cues.append({"op": "show_setup", "static": {"fmt": "duel", "need": 0, "sides": {}, "fighters_static": {}},
                 "crowd": arena.crowd, "odds": {}})
    cues.append({"op": "music", "track": ep.get("hook_music", "tension"), "fade_in": 0.2, "volume": 0.55})
    cues.append({"op": "show_card", "kind": "hook", "duration": 3.4, "cheer": 3.4, "lines": hook,
                 "tag": ep.get("tag", "REAL DICE  /  NO REROLLS  /  EVERY ROLL LOGGED"),
                 "col_top": list(ep.get("col_top", S.A_COL)), "col_bottom": list(ep.get("col_bottom", S.B_COL)),
                 "sfx": [[0.0, "hit_heavy"], [0.25, "hit_heavy"], [0.6, "crit"]], "meta": {"mark": "hook"}})
    kind = ep["kind"]
    mark = {"cta": cta}
    if kind in ("duel",):
        c, first_static = best_of_cues(seg0, music, mark)
        cues += c
    elif kind == "how_many":
        cues += how_many_cues(seg0, ep, music, mark)
    elif kind == "rumble":
        cues += rumble_cues(seg0, ep, music, mark)
    elif kind in ("crown_semis", "crown_final"):
        cues += crown_cues(season, ep, res, results, music, mark)
    # Results.
    if kind not in ("crown_semis", "crown_final"):
        if cues[-1]["op"] == "show_reset":
            cues = cues[:-2]                       # keep the last fight on screen behind the result
    cues.append({"op": "music_stop", "fade_out": 0.4})
    cues.append({"op": "music", "track": "theme", "fade_in": 0.4, "volume": 0.5})
    cues += result_cards(season, ep, res, results)
    # Road to the Crown.
    if ep.get("road", True):
        cues.append({"op": "show_card", "kind": "road", "duration": 7.0, "slots": road_slots(season, n, results),
                     "pairs": season["crown"]["pairs"], "line": ep.get("road_line"),
                     "pair_line": season["crown"]["pair_line"], "sfx": [[0.0, "transition"], [2.6, "buff"]],
                     "meta": {"mark": "road"}})
    # End screen.
    if nxt:
        nseg = nxt
        cues.append({"op": "show_card", "kind": "next", "duration": ep.get("end_s", 16.0),
                     "title": nseg["title"].upper(), "when": nice_date(nseg["date"]),
                     "a_sprite": nseg.get("a") or nseg.get("star") or nseg.get("thumb_a"),
                     "b_sprite": nseg.get("b") or nseg.get("minion_sprite") or nseg.get("minion") or nseg.get("thumb_b"),
                     "foot": season["end_foot"], "foot2": (season.get("unlock") or {}).get("line"),
                     "sfx": [[0.0, "transition"]], "meta": {"mark": "end"}})
    else:
        cues.append({"op": "show_card", "kind": "next", "duration": ep.get("end_s", 16.0), "kicker": "THANK YOU FOR WATCHING",
                     "title": season.get("finale_next_title", "SEASON 2: THE SILVER CROWN"),
                     "when": season.get("finale_next_when", "NOMINATE A FIGHTER IN THE COMMENTS"),
                     "a_sprite": None, "foot": season["end_foot"],
                     "foot2": None if ep.get("bonus") else (season.get("unlock") or {}).get("line"),
                     "sfx": [[0.0, "transition"]], "meta": {"mark": "end"}})
    cues.append({"op": "music_stop", "fade_out": 0.8})
    cues.append({"op": "fade", "to": "black", "duration": 0.6})
    return {"schema": "pqc/timeline@1", "id": f"pit-s1e{n:02d}", "title": ep["title"], "fps": 30, "seed": ep["seed"],
            "tail": 0.2, "cues": cues}


def result_cards(season: dict, ep: dict, res: dict, results: dict) -> list[dict]:
    kind = ep["kind"]
    out = []
    seg = res["segments"][0]
    if kind == "duel":
        m = seg["match"]
        w = winner_of(seg)
        lo = loser_of(seg)
        col = S.A_COL if m["winner"] == "a" else S.B_COL
        sc = sorted(m["score"], reverse=True)
        out.append({"op": "show_card", "kind": "result", "duration": 8.0, "cheer": 8.0, "sprite": w["sprite"],
                    "name": w["name"], "col": list(col), "line": f"{sc[0]} - {sc[1]}  over {lo['name']}",
                    "rows": match_stats(seg), "cols": [list(S.A_COL), list(S.B_COL)],
                    "names": [seg["a"][0]["name"], seg["b"][0]["name"]],
                    "stamp": "QUALIFIES FOR THE BRONZE CROWN" if ep.get("qualifier") else None,
                    "foot": ep.get("result_foot"), "sfx": [[0.0, "level_up"], [2.6, "nat20"]] if ep.get("qualifier")
                    else [[0.0, "level_up"]], "meta": {"mark": "result"}})
    elif kind == "how_many":
        star = seg["star"]
        plural = ep.get("plural", seg["minion_name"] + "s")
        rows = []
        for r in seg["rounds"]:
            won = r["winner"] == "a"
            hp_left = next((c["hp"] for c in r["events"][-1]["survivors"] if c["id"] == "star"), 0) \
                if r["events"][-1]["t"] == "encounter_end" else 0
            rows.append([f"ROUND {len(rows) + 1}: {r['count']} {plural.upper()}",
                         f"SURVIVED ({hp_left} HP LEFT)" if won else "DEFEATED", S.GREEN if won else S.RED])
        ans = seg["answer"]
        line = (f"It took {ans} {plural.lower()}." if ans else f"Not even {seg['counts'][-1]} {plural.lower()} could do it.")
        out.append({"op": "show_card", "kind": "result", "duration": 8.0, "cheer": 6.0,
                    "sprite": seg.get("minion_sprite", seg["minion"]) if ans else star["sprite"], "kicker": "THE ANSWER",
                    "name": f"{ans} {plural}" if ans else f"MORE THAN {seg['counts'][-1]}", "col": list(S.B_COL if ans else S.A_COL),
                    "line": line, "rows": rows, "row_kind": "list", "foot": ep.get("result_foot"),
                    "sfx": [[0.0, "level_up"]], "meta": {"mark": "result"}})
    elif kind == "rumble":
        w = winner_of(seg)
        order = elimination_order(seg)
        names = {f["id"]: f["name"] for f in seg["fighters"]}
        cols = {f["id"]: S.FFA_COLS[i % len(S.FFA_COLS)] for i, f in enumerate(seg["fighters"])}
        rows = []
        place = len(seg["fighters"])
        for fid in order:
            rows.append([f"{place}{'TH' if place > 3 else {1: 'ST', 2: 'ND', 3: 'RD'}[place]} PLACE", names[fid].upper(), cols[fid]])
            place -= 1
        rows = rows[::-1][:6]
        out.append({"op": "show_card", "kind": "result", "duration": 8.0, "cheer": 8.0, "sprite": w["sprite"],
                    "name": w["name"], "col": list(cols[w["id"]]), "kicker": "LAST ONE STANDING",
                    "line": ep.get("result_line", f"Outlasted {len(seg['fighters']) - 1} others."),
                    "rows": rows, "row_kind": "list", "stamp": "QUALIFIES FOR THE BRONZE CROWN" if ep.get("qualifier") else None,
                    "foot": ep.get("result_foot"), "sfx": [[0.0, "level_up"]] + ([[2.6, "nat20"]] if ep.get("qualifier") else []),
                    "meta": {"mark": "result"}})
    return out


def crown_cues(season, ep, res, results, music, mark) -> list[dict]:
    """Semifinals (two matches) or the final, with the bracket between them."""
    cues = []
    q = qualifiers(season, ep["n"], results)
    ents = []
    probs = res.get("crown_odds", {})
    (a0, a1), (b0, b1) = season["crown"]["pairs"]
    for i in (a0, a1, b0, b1):
        w = q[i]
        ents.append({"sprite": w["sprite"], "name": w["name"], "p": probs.get(w["monster"], 0.25)})
    semis_known = [None, None]
    champion = None
    if ep["kind"] == "crown_final":
        semis = results[ep["depends"][-1]]["segments"]
        for k in range(2):
            w = winner_of(semis[k])
            semis_known[k] = {"sprite": w["sprite"], "name": w["name"]}
        m0 = res["segments"][0]["match"]
        fa, fb = res["segments"][0]["a"][0]["name"], res["segments"][0]["b"][0]["name"]
        for e in ents:
            e["out"] = not any(s and s["name"] == e["name"] for s in semis_known)
            if e["name"] == fa:
                e["p"] = m0["p_match"]
            elif e["name"] == fb:
                e["p"] = 1 - m0["p_match"]
    labels = ["SEMIFINAL 1", "SEMIFINAL 2"]
    cues.append({"op": "show_card", "kind": "bracket", "duration": 6.0, "entrants": [dict(e) for e in ents],
                 "semis": [dict(x) if x else None for x in semis_known],
                 "semi_labels": labels, "title": "THE BRONZE CROWN", "sub": ep.get("bracket_sub", ""),
                 "line": ep.get("bracket_line"), "sfx": [[0.0, "transition"]], "meta": {"mark": "bracket"}})
    for k, seg in enumerate(res["segments"]):
        c, _ = best_of_cues(seg, music, {**mark, "cta": mark["cta"] if k == 0 else None, "seg": k})
        cues += c
        cues = cues[:-2] if cues[-1]["op"] == "show_reset" else cues
        w = winner_of(seg)
        lo = loser_of(seg)
        m = seg["match"]
        col = S.A_COL if m["winner"] == "a" else S.B_COL
        sc = sorted(m["score"], reverse=True)
        if ep["kind"] == "crown_semis":
            semis_known[k] = {"sprite": w["sprite"], "name": w["name"]}
            for e in ents:
                if e["name"] == lo["name"]:
                    e["out"] = True
            cues.append({"op": "show_card", "kind": "result", "duration": 6.0, "cheer": 6.0, "sprite": w["sprite"],
                         "name": w["name"], "col": list(col), "kicker": f"SEMIFINAL {k + 1}",
                         "line": f"{sc[0]} - {sc[1]}  over {lo['name']}", "rows": match_stats(seg),
                         "cols": [list(S.A_COL), list(S.B_COL)], "names": [seg["a"][0]["name"], seg["b"][0]["name"]], "stamp": "THROUGH TO THE FINAL",
                         "sfx": [[0.0, "level_up"], [2.6, "nat20"]], "meta": {"mark": "result", "seg": k}})
            cues.append({"op": "fade", "to": "black", "duration": 0.25})
            cues.append({"op": "show_reset", "fighters": ["a1", "b1"]})
            cues.append({"op": "fade", "from": "black", "to": "clear", "duration": 0.25, "wait": False})
            cues.append({"op": "show_card", "kind": "bracket", "duration": 4.5, "entrants": [dict(e) for e in ents],
                         "semis": [dict(s) if s else None for s in semis_known], "semi_labels": labels,
                         "title": "THE BRONZE CROWN", "sub": "", "final_label": ep.get("final_label", "FINAL: SAT 21 NOV"),
                         "line": None if k == 0 else ep.get("bracket_end_line"), "sfx": [[0.0, "transition"]],
                         "meta": {"mark": "bracket", "seg": k}})
        else:
            champion = {"sprite": w["sprite"], "name": w["name"]}
            cues.append({"op": "music_stop", "fade_out": 0.3})
            cues.append({"op": "music", "track": "theme", "fade_in": 0.3, "volume": 0.55})
            cues.append({"op": "show_card", "kind": "crown", "duration": 7.0, "cheer": 7.0, "sprite": w["sprite"],
                         "name": w["name"], "line": f"Won the final {sc[0]} - {sc[1]} over {lo['name']}.",
                         "foot": "The first Bronze Crown of the Pit.", "flash": True,
                         "sfx": [[0.0, "level_up"], [0.5, "nat20"], [1.0, "victory"]], "meta": {"mark": "crown"}})
            cues.append({"op": "show_card", "kind": "result", "duration": 7.0, "sprite": w["sprite"], "name": w["name"],
                         "col": list(col), "kicker": "FINAL", "line": f"{sc[0]} - {sc[1]}  over {lo['name']}",
                         "rows": match_stats(seg), "cols": [list(S.A_COL), list(S.B_COL)],
                    "names": [seg["a"][0]["name"], seg["b"][0]["name"]], "sfx": [],
                         "meta": {"mark": "result"}})
            cues.append({"op": "show_card", "kind": "bracket", "duration": 4.5, "entrants": [dict(e) for e in ents],
                         "semis": [dict(x) if x else None for x in semis_known], "semi_labels": labels, "champion": champion, "title": "THE BRONZE CROWN",
                         "sub": "SEASON 1", "line": None, "sfx": [[0.0, "transition"]], "meta": {"mark": "bracket"}})
            if season.get("season2"):
                s2 = season["season2"]
                cues.append({"op": "show_card", "kind": "text", "duration": 9.0, "title": s2["title"],
                             "lines": s2["lines"], "button": True, "sfx": [[0.0, "transition"], [1.5, "buff"]],
                             "meta": {"mark": "season2"}})
    return cues


# ============================================================ crown odds
def crown_odds(entrants: list[str], arena: Arena, n: int, need: list[int]) -> dict[str, float]:
    """Each entrant's chance to win the Crown (bracket order), from n fights per pairing."""
    p = {}
    for i, x in enumerate(entrants):
        for y in entrants[i + 1:]:
            fs = [fighter(x, "a1", "a", DUEL_POS["a"]), fighter(y, "b1", "b", DUEL_POS["b"])]
            q = formats.fresh_odds(fs, n, arena.blocked, tag=f"crown-{x}-{y}")["a"]
            p[(x, y)], p[(y, x)] = q, 1 - q
    return formats.tournament_odds(entrants, p, need)
