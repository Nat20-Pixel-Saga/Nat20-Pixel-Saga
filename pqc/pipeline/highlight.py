"""Pick each episode's highlight for its YouTube Short.

The episode's timeline is replayed at the Short's faster reading pace (no
drawing, a second or two), every cue is scored (natural 20s and 1s, death
saves, a party member going down or getting back up, decisive social checks,
fights won), and the best 25-55 second stretch of consecutive cues inside one
scene is chosen. A hand-tuned window in assets/shorts/<campaign>.json wins over
the automatic pick.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..state import ROOT

SHORT_READING = {"cps": 34.0, "hold_base": 0.9, "hold_per_char": 0.018}
MIN_S, MAX_S, TARGET_S = 25.0, 55.0, 42.0
SPECS = ROOT / "assets" / "shorts"
PARTY = ("brannoc", "ilsevel", "tamsin", "oriel")
SOCIAL = ("Persuasion", "Deception", "Insight", "Intimidation", "Performance")


def short_spec(eid: str) -> dict:
    f = SPECS / f"{eid[:3].lower()}.json"
    return json.loads(f.read_text()).get(eid, {}) if f.exists() else {}


def cue_times(timeline: dict, assets=None) -> tuple[list[float], float]:
    """Start time of every cue at the Short's reading pace, and the total length."""
    from ..render.assets import Assets
    from ..render.timeline import Runner
    tl = dict(timeline)
    tl["reading"] = {**timeline.get("reading", {}), **SHORT_READING}
    r = Runner(tl, assets or Assets())
    total = r.duration()
    return r.cue_times, total


def score_cue(c: dict) -> tuple[float, str | None]:
    """How strong a moment this cue is, and what kind."""
    op = c["op"]
    roll = c.get("roll") or {}
    label = c.get("label", "")
    if op == "battle_faint":
        return (9.0, "down") if c.get("pc") or c.get("actor") in PARTY else (2.0, "kill")
    if op == "battle_revive":
        return 7.0, "revive"
    if roll:
        if "death save" in (roll.get("purpose") or "") or "Death save" in label:
            return 9.0, "death_save"
        if roll.get("natural") == 20 or roll.get("critical") or c.get("critical"):
            return 10.0, "nat20"
        if roll.get("natural") == 1 or roll.get("fumble"):
            return 8.0, "nat1"
        if any(k in label for k in SOCIAL):
            return (4.5, "social") if roll.get("success") else (3.5, "social_fail")
        return 1.0, None
    if op == "say":
        return 0.6, None
    if op == "battle_start":
        return 2.0, "fight"
    return 0.0, None


BREAKS = ("scene", "fade", "dm_intro", "title")


def pick(timeline: dict, times: list[float], total: float, spec: dict | None = None) -> dict:
    """The Short's window: cues [start, end), with its length and the moment it's built around."""
    cues = timeline["cues"]
    n = len(cues)
    ends = times[1:] + [total]
    spec = spec or {}
    if "start_cue" in spec and "end_cue" in spec:
        a, b = spec["start_cue"], spec["end_cue"]
        best = (0.0, a, b)
    else:
        scores = [score_cue(c)[0] for c in cues]
        best = None
        for a in range(n):
            if cues[a]["op"] not in ("say", "narrate", "battle_start", "roll") or times[a] < 1.0:
                continue
            s = 0.0
            for b in range(a + 1, n + 1):
                c = cues[b - 1]
                if c["op"] in BREAKS and b - 1 > a:
                    break
                s += scores[b - 1]
                dur = ends[b - 1] - times[a]
                if dur > MAX_S:
                    break
                if dur < MIN_S or c["op"] not in ("say", "narrate"):
                    continue          # end on a line, after the moment has landed
                val = s - 0.04 * abs(dur - TARGET_S) + (0.8 if c["op"] == "say" else 0.0)
                if best is None or val > best[0]:
                    best = (val, a, b)
        if best is None:                                   # fallback: first 40 s after the title
            a = next(i for i, c in enumerate(cues) if c["op"] in ("say", "narrate"))
            b = a + 1
            while b < n and ends[b - 1] - times[a] < 40:
                b += 1
            best = (0.0, a, b)
    _, a, b = best
    kinds = [(score_cue(cues[i]), i) for i in range(a, b)]
    (sc, kind), anchor = max(kinds, key=lambda x: x[0][0])
    actors = []
    for i in range(a, b):
        who = cues[i].get("speaker") or cues[i].get("actor")
        if who and who not in actors and not str(who).startswith(("goblin-", "wolf-")):
            actors.append(who)
    return {"start_cue": a, "end_cue": b, "duration_s": round(ends[b - 1] - times[a], 2),
            "anchor_cue": spec.get("anchor_cue", anchor), "kind": kind or "story",
            "speakers": actors, "reading": SHORT_READING}


def transcript(timeline: dict, window: dict) -> str:
    """The lines and rolls of the window, for the packager's prompt."""
    out = []
    for c in timeline["cues"][window["start_cue"]:window["end_cue"]]:
        if c["op"] in ("say", "narrate"):
            who = (c.get("speaker") or "Narrator").replace("_", " ").title()
            out.append(f"{who}: {c['text']}")
        elif c.get("label"):
            out.append(f"[{c['label']}: {c.get('line', '')}]".replace(": ]", "]"))
        elif c["op"] == "battle_faint":
            out.append(f"[{c.get('actor')} falls]")
        elif c["op"] == "battle_revive":
            out.append(f"[{c.get('actor')} gets back up]")
    return "\n".join(out)


def highlight(eid: str, timeline: dict, assets=None) -> dict:
    times, total = cue_times(timeline, assets)
    return pick(timeline, times, total, short_spec(eid))
