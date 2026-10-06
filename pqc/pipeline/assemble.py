"""Assemble the episode timeline: plan + script + resolved dice -> renderer cues.

The writer only writes story cues. Everything mechanical is added here:
title card, the Storyteller's intro, scene cuts and location cards, the cast's
marks, walking paths around props, the dice tray for each check (from the
logged roll), the whole fight (from the director), the "Next time" line and
chapter markers. Problems are collected rather than raised so the continuity
step can report them all at once.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from .. import features
from ..state import ROOT, load_json
from .resolve import MANIFEST, Resolution, blocked_squares, load_map

MAX_BOX = 140
EMOTES = {"neutral", "happy", "smile", "sad", "shock", "sweat", "dots", "exclaim", "alert", "question", "question_red",
          "heartbreak", "love", "angry", "plus"}
FACINGS = {"up", "down", "left", "right"}
PRESETS = {"day", "morning", "dusk", "evening", "night"}
PARTY_NAMES = {"brannoc": "Brannoc", "ilsevel": "Ilsevel", "tamsin": "Tamsin", "oriel": "Oriel"}


@dataclass
class Assembly:
    timeline: dict
    problems: list[str] = field(default_factory=list)
    placed: dict[str, int] = field(default_factory=dict)   # check/encounter id -> times placed


# ---------------------------------------------------------------- walking
def walk_path(map_id: str, start, goal, extra_blocked=frozenset()) -> list[list[int]]:
    """Shortest walk from ``start`` to ``goal`` around props, as waypoints
    (only the corners). Squares off the map edge are allowed so actors can
    enter and leave the screen."""
    m = load_map(map_id)
    w, h = m["size"]
    blocked = blocked_squares(map_id) | set(extra_blocked)
    start, goal = tuple(start[:2]), tuple(goal[:2])

    def ok(sq):
        x, y = sq
        if sq in (start, goal):
            return True
        if not (-3 <= x < w + 3 and -3 <= y < h + 3):
            return False
        return sq not in blocked

    dist = {start: 0}
    prev = {}
    heap = [(0, start)]
    while heap:
        d, sq = heapq.heappop(heap)
        if sq == goal:
            break
        if d > dist[sq]:
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not dx and not dy:
                    continue
                nxt = (sq[0] + dx, sq[1] + dy)
                if not ok(nxt):
                    continue
                if dx and dy and (not ok((sq[0] + dx, sq[1])) or not ok((sq[0], sq[1] + dy))):
                    continue  # don't cut a prop's corner
                nd = d + (14 if dx and dy else 10)
                if nd < dist.get(nxt, 1 << 30):
                    dist[nxt] = nd
                    prev[nxt] = sq
                    heapq.heappush(heap, (nd, nxt))
    if goal not in dist:
        return [list(goal)]
    path = [goal]
    while path[-1] != start:
        path.append(prev[path[-1]])
    path.reverse()
    # Keep only the corners.
    pts = [path[0]]
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
            pts.append(b)
    pts.append(path[-1])
    return [list(p) for p in pts[1:]] or [list(goal)]


def split_box(text: str, limit: int = MAX_BOX) -> list[str]:
    """Split a long line at sentence (then word) boundaries."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    import re
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(sentence) > limit:
            words, sentence_parts, buf = sentence.split(), [], ""
            for wd in words:
                if len(buf) + len(wd) + 1 > limit:
                    sentence_parts.append(buf)
                    buf = wd
                else:
                    buf = f"{buf} {wd}".strip()
            sentence_parts.append(buf)
        else:
            sentence_parts = [sentence]
        for part in sentence_parts:
            if cur and len(cur) + len(part) + 1 > limit:
                out.append(cur)
                cur = part
            else:
                cur = f"{cur} {part}".strip()
    if cur:
        out.append(cur)
    return out


def _edge_entry(map_id: str, at) -> list[int]:
    """The off-map square nearest ``at``: where someone arriving from outside spawns."""
    w, h = load_map(map_id)["size"]
    x, y = at[0], at[1]
    options = [(x, -1, y), (x, h, h - 1 - y), (-1, y, x), (w, y, w - 1 - x)]
    ex, ey, _ = min(options, key=lambda o: o[2])
    return [ex, ey]


# ---------------------------------------------------------------- assemble
def assemble(plan: dict, script: dict, res: Resolution, check_cues: dict[str, list[dict]], sheets: dict,
             episode_no: int | None = None) -> Assembly:
    man = load_json(MANIFEST)
    sprites, sfx_ids, music_ids = set(man["actors"]), set(man["sfx"]), set(man["music"])
    problems: list[str] = []
    placed: dict[str, int] = {}
    cues: list[dict] = []
    chapters: list[dict] = []
    on_stage: dict[str, dict] = {}   # id -> {"at": [x, y], "down": bool}
    scenes = {s["id"]: s for s in script["scenes"]}
    battles = res.battles
    n = episode_no or int(plan["episode_id"][-3:])
    names = {**PARTY_NAMES}

    # ---- cold open, title
    if script.get("cold_open"):
        chapters.append({"cue": 0, "title": "Previously"})
        for c in script["cold_open"]:
            for part in split_box(c.get("text", "")):
                cues.append({"op": "narrate", "text": part})
    chapters.append({"cue": len(cues), "title": "Title"})
    camp = int(plan["episode_id"][1:3])     # the show's name is in the common intro just before this card
    cues.append({"op": "title", "lines": [plan["title"], f"Campaign {camp}  -  Episode {n}"], "duration": 2.6})

    cur_map, cur_tod, cur_music = None, None, None
    framer = Framer(plan["scenes"][0]["map"])
    for i, sc in enumerate(plan["scenes"]):
        s_script = scenes.get(sc["id"])
        if s_script is None:
            problems.append(f"{sc['id']}: the script has no cues for this scene")
            continue
        cont = i > 0 and sc.get("transition") == "continue" and sc["map"] == cur_map
        chapters.append({"cue": len(cues), "title": sc["name"]})
        if not cont:
            if i > 0:
                cues.append({"op": "fade", "to": "black", "duration": 0.7})
                if cur_music:
                    cues.append({"op": "music_stop", "fade_out": 0.6, "wait": False})
            cues.append({"op": "scene", "map": sc["map"], "time_of_day": sc["time_of_day"],
                         "camera": sc.get("camera") or sc["cast"][0]["at"]})
            framer = Framer(sc["map"])
            framer.cam = list(sc.get("camera") or sc["cast"][0]["at"])
            on_stage.clear()
            for c in sc["cast"]:
                sprite = c.get("sprite", c["id"])
                cues.append({"op": "spawn", "actor": c["id"], "sprite": sprite, "at": c["at"][:2],
                             "facing": c.get("facing", "down"), "name": c.get("name", c["id"])})
                on_stage[c["id"]] = {"at": list(c["at"][:2]), "down": False}
                names[c["id"]] = c.get("name", c["id"]).split()[0]
            cues.append({"op": "fade", "from": "black", "to": "clear", "duration": 0.9, "wait": False})
            if i == 0:
                cues.append({"op": "dm_intro", **plan["dm_intro"]})
            cur_map, cur_tod = sc["map"], sc["time_of_day"]
        else:
            if sc["time_of_day"] != cur_tod:
                cues.append({"op": "time_of_day", "preset": sc["time_of_day"], "duration": 2.0, "wait": False})
                cur_tod = sc["time_of_day"]
            if sc.get("camera"):
                cues.append({"op": "camera", "to": sc["camera"], "duration": 1.0, "wait": False})
                framer.cam = list(sc["camera"])
            # Same place, no cut: whoever is already on screen stays where the
            # last scene (or fight) left them; the writer moves them. Only
            # newcomers are placed on their marks.
            for c in sc["cast"]:
                if c["id"] not in on_stage:
                    sprite = c.get("sprite", c["id"])
                    cues.append({"op": "spawn", "actor": c["id"], "sprite": sprite, "at": c["at"][:2],
                                 "facing": c.get("facing", "down"), "name": c.get("name", c["id"])})
                    on_stage[c["id"]] = {"at": list(c["at"][:2]), "down": False}
        music = sc.get("music")
        if music and music != cur_music or (music and not cont):
            if music not in music_ids:
                problems.append(f"{sc['id']}: unknown music {music!r}")
            else:
                cues.append({"op": "music", "track": music, "fade_in": 1.0, "volume": 0.45})
                cur_music = music
        loc = load_map(sc["map"]).get("name", sc["map"])
        cues.append({"op": "location_card", "text": f"{loc}  -  {sc['name']}  -  {sc['time_of_day'].title()}",
                     "duration": 3.0})
        if not cont and i == 0:
            cues.append({"op": "wait", "seconds": 0.4})

        # ---- the writer's cues
        for k, c in enumerate(s_script["cues"]):
            where = f"{sc['id']}#{k}"
            op = c.get("op")
            if op in ("say", "narrate"):
                if op == "say" and c.get("speaker") not in on_stage:
                    problems.append(f"{where}: speaker {c.get('speaker')!r} is not on stage")
                    continue
                if op == "say" and on_stage[c["speaker"]]["down"]:
                    problems.append(f"{where}: {c['speaker']} is unconscious and can't speak")
                if c.get("emote") and c["emote"] not in EMOTES:
                    problems.append(f"{where}: unknown emote {c['emote']!r}")
                if op == "say":
                    cam = framer.frame(c["speaker"], on_stage)
                    if cam:
                        cues.append(cam)
                parts = split_box(c.get("text", ""))
                for j, part in enumerate(parts):
                    cue = {"op": op, "text": part}
                    if op == "say":
                        cue["speaker"] = c["speaker"]
                        if j == 0 and c.get("emote") in EMOTES:
                            cue["emote"] = c["emote"]
                    cues.append(cue)
            elif op == "move":
                a = c.get("actor")
                if a not in on_stage:
                    problems.append(f"{where}: {a!r} is not on stage")
                    continue
                if on_stage[a]["down"]:
                    problems.append(f"{where}: {a} is unconscious and can't walk")
                    continue
                goal = c.get("to") or (c.get("path") or [[None]])[-1]
                if not goal or goal[0] is None:
                    problems.append(f"{where}: move needs 'to'")
                    continue
                path = walk_path(sc["map"], on_stage[a]["at"], goal, _others(on_stage, a))
                cue = {"op": "move", "actor": a, "path": path, "speed": c.get("speed", 4)}
                if c.get("face") in FACINGS:
                    cue["face"] = c["face"]
                if c.get("wait") is False:
                    cue["wait"] = False
                cues.append(cue)
                on_stage[a]["at"] = list(goal[:2])
            elif op == "face":
                if c.get("actor") not in on_stage or c.get("facing") not in FACINGS:
                    problems.append(f"{where}: bad face cue {c}")
                    continue
                cues.append({"op": "face", "actor": c["actor"], "facing": c["facing"]})
            elif op == "emote":
                if c.get("actor") not in on_stage or c.get("emote") not in EMOTES:
                    problems.append(f"{where}: bad emote cue {c}")
                    continue
                cue = {"op": "emote", "actor": c["actor"], "emote": c["emote"], "duration": c.get("duration", 1.2)}
                if c.get("sfx") in sfx_ids:
                    cue["sfx"] = c["sfx"]
                cues.append(cue)
            elif op == "spawn":
                sprite = c.get("sprite", c.get("actor"))
                if sprite not in sprites:
                    problems.append(f"{where}: unknown sprite {sprite!r}")
                    continue
                cues.append({"op": "spawn", "actor": c["actor"], "sprite": sprite, "at": c["at"][:2],
                             "facing": c.get("facing", "down"), "name": c.get("name", c["actor"])})
                on_stage[c["actor"]] = {"at": list(c["at"][:2]), "down": False}
                names[c["actor"]] = c.get("name", c["actor"]).split()[0]
            elif op == "despawn":
                on_stage.pop(c.get("actor"), None)
                cues.append({"op": "despawn", "actor": c.get("actor")})
            elif op == "camera":
                cues.append({"op": "camera", "to": c["to"][:2], "duration": c.get("duration", 1.2),
                             **({"wait": False} if c.get("wait") is False else {})})
                framer.cam = list(c["to"][:2])
            elif op == "lantern":
                cue = {k: v for k, v in c.items() if k in ("op", "id", "state", "flicker", "unlight", "sfx")}
                cue.setdefault("flicker", 1.6)
                if cue.get("state") == "dead" and "unlight" not in cue:
                    cue["unlight"] = {"radius": 70, "grow": 3.0, "strength": 0.6}
                cues.append(cue)
            elif op == "time_of_day":
                if c.get("preset") not in PRESETS:
                    problems.append(f"{where}: unknown time of day {c.get('preset')!r}")
                    continue
                cues.append({"op": "time_of_day", "preset": c["preset"], "duration": c.get("duration", 2.5),
                             "wait": c.get("wait", False)})
                cur_tod = c["preset"]
            elif op == "sfx":
                if c.get("id") in sfx_ids:
                    cues.append({"op": "sfx", "id": c["id"]})
                else:
                    problems.append(f"{where}: unknown sfx {c.get('id')!r}")
            elif op in ("music", "music_stop"):
                if op == "music" and c.get("track") not in music_ids:
                    problems.append(f"{where}: unknown music {c.get('track')!r}")
                    continue
                cues.append({k: v for k, v in c.items() if k in ("op", "track", "fade_in", "fade_out", "volume")})
                cur_music = c.get("track") if op == "music" else None
            elif op == "wait":
                cues.append({"op": "wait", "seconds": min(3.0, float(c.get("seconds", 0.5)))})
            elif op == "location_card":
                cues.append({"op": "location_card", "text": c.get("text", ""), "duration": 3.0})
            elif op == "check":
                cid = c.get("id")
                placed[cid] = placed.get(cid, 0) + 1
                if cid not in check_cues:
                    problems.append(f"{where}: unknown check {cid!r}")
                    continue
                for rc in check_cues[cid]:
                    if rc["op"] == "battle_revive":
                        a = rc["actor"]
                        if a in on_stage:
                            on_stage[a]["down"] = False
                    cues.append(rc)
            elif op == "encounter":
                eid = c.get("id")
                placed[eid] = placed.get(eid, 0) + 1
                if eid not in battles:
                    problems.append(f"{where}: unknown encounter {eid!r}")
                    continue
                cues += _battle(sc, plan, eid, battles[eid], s_script.get("battle_narration", []), on_stage, names,
                                problems)
                cur_music = None
                framer.cam = None  # wherever the fight left it
            else:
                problems.append(f"{where}: unknown op {op!r}")

    cues.append({"op": "wait", "seconds": 0.6})
    chapters.append({"cue": len(cues), "title": "Next time"})
    cues.append({"op": "narrate", "text": f"Next time: {script.get('next_time') or plan['next_time']}"})
    card = progress_cue(plan["episode_id"], res, sheets)
    if card:
        cues.append(card)
    cues.append({"op": "music_stop", "fade_out": 1.5, "wait": False})
    cues.append({"op": "fade", "to": "black", "duration": 1.4})
    timeline = {"schema": "pqc/timeline@1", "id": plan["episode_id"], "title": f"{plan['episode_id']} - {plan['title']}",
                "fps": 30, "seed": res.episode["seed"], "tail": 0.4, "cues": cues, "chapters": chapters}
    return Assembly(timeline, problems, placed)


def progress_cue(eid: str, res: Resolution, sheets: dict) -> dict | None:
    """The party's levels and XP before the outro (production/show.json "progress_card"): shown when
    anyone gained XP or a level, and at least every N episodes. Only from the episode in
    production/features.json, and only if the resolver recorded progress."""
    prog = res.episode.get("progress")
    if not prog or not features.enabled("progress_card", eid):
        return None
    cfg = load_json(ROOT / "production" / "show.json")["progress_card"]
    changed = any(p["xp"] != p["xp_before"] or p["level"] != p["level_before"] for p in prog.values())
    if not ((cfg.get("on_change", True) and changed) or int(eid[-3:]) % cfg.get("every", 3) == 0):
        return None
    from .. import progression
    new = {r["id"]: r for r in res.episode.get("level_ups", [])}
    party = []
    for cid in PARTY_ORDER:
        if cid not in prog:
            continue
        p, s = prog[cid], res.sheets_after[cid]
        party.append({
            "id": cid, "name": s["name"].split()[0], "title": f"{s['species'].replace('_', ' ').title()} "
                                                             f"{s['class'].title()}",
            "level_before": p["level_before"], "level": p["level"], "xp_before": p["xp_before"], "xp": p["xp"],
            "from_start": progression.xp_for_level(p["level_before"]),
            "from_next": progression.xp_for_level(p["level_before"] + 1),
            "level_start": p["level_start"], "next_at": p["next_at"],
            "new": list(dict.fromkeys(_short(g) for g in (new.get(cid) or {}).get("new", [])))})
    up = any(m["level"] > m["level_before"] for m in party)
    return {"op": "progress", "title": "The party", "subtitle": f"After Episode {int(eid[-3:])}",
            "party": party, "duration": cfg.get("seconds_level_up" if up else "seconds", 7.5 if up else 5.5)}


PARTY_ORDER = ("brannoc", "ilsevel", "tamsin", "oriel")


def _short(gain: str) -> str:
    """A level-up gain as the card shows it: "New spell in the book: Fog Cloud" -> "Fog Cloud"."""
    for prefix in ("New spell in the book: ", "Prepares ", "New cantrip: ", "Subclass: ", "Ability Score Improvement: "):
        if gain.startswith(prefix):
            return gain[len(prefix):]
    if gain.startswith("Expertise in "):
        return gain[len("Expertise in "):] + " Expertise"
    return gain


def _path_len(move: dict) -> float:
    pts = [move["_from"]] + move["path"]
    return sum(max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(pts, pts[1:]))


class Framer:
    """Keeps whoever is talking on screen: the viewport is 15 x 8.4 tiles and the
    dialog box covers its bottom two, so a speaker must sit within ~6 tiles
    sideways and between 2.5 tiles above and 1.5 below the camera centre."""

    SAFE_X, SAFE_UP, SAFE_DOWN = 6.0, 2.5, 1.5

    def __init__(self, map_id: str):
        self.w, self.h = load_map(map_id)["size"]
        self.cam: list[float] | None = None
        self.last_speaker: str | None = None

    def _clamp(self, cx, cy):
        return min(max(cx, 7.5), self.w - 7.5), min(max(cy, 4.2), self.h - 4.2)

    def visible(self, at) -> bool:
        if self.cam is None:
            return False
        cx, cy = self._clamp(*self.cam)
        return abs(at[0] - cx) <= self.SAFE_X and -self.SAFE_UP <= at[1] - cy <= self.SAFE_DOWN

    def frame(self, speaker: str, on_stage: dict) -> dict | None:
        """A camera cue if the speaker is off the safe area, else None. Frames the
        speaker together with the previous speaker when both fit."""
        at = on_stage[speaker]["at"]
        other = on_stage.get(self.last_speaker, {}).get("at") if self.last_speaker != speaker else None
        self.last_speaker = speaker
        if self.visible(at):
            return None
        target = [at[0], at[1] + 0.5]
        if other and abs(other[0] - at[0]) <= 2 * self.SAFE_X - 2 and abs(other[1] - at[1]) <= 3:
            target = [(at[0] + other[0]) / 2, (at[1] + other[1]) / 2 + 0.5]
        self.cam = target
        return {"op": "camera", "to": [round(target[0]), round(target[1])], "duration": 0.9}


def _others(on_stage: dict, me: str) -> set:
    return {tuple(v["at"]) for k, v in on_stage.items() if k != me}


def _battle(sc: dict, plan: dict, eid: str, battle: dict, narration: list[dict], on_stage: dict, names: dict,
            problems: list[str]) -> list[dict]:
    enc = sc.get("encounter")
    if not enc or enc["id"] != eid:
        enc = next(s["encounter"] for s in plan["scenes"] if s.get("encounter") and s["encounter"]["id"] == eid)
    out: list[dict] = []
    # 1. Take positions: the party walks to its marks, the enemies arrive from the nearest edge.
    walkers = []
    for pid, xy in enc["party_at"].items():
        if pid not in on_stage:
            problems.append(f"{eid}: {pid} must be on stage before the fight")
            out.append({"op": "spawn", "actor": pid, "sprite": pid, "at": xy[:2], "facing": "down",
                        "name": PARTY_NAMES.get(pid, pid)})
            on_stage[pid] = {"at": list(xy[:2]), "down": False}
        elif on_stage[pid]["at"] != list(xy[:2]):
            walkers.append({"op": "move", "actor": pid, "speed": 5, "_from": on_stage[pid]["at"],
                            "path": walk_path(sc["map"], on_stage[pid]["at"], xy, _others(on_stage, pid)),
                            "wait": False})
            on_stage[pid]["at"] = list(xy[:2])
    for e in enc["enemies"]:
        if e["id"] not in on_stage:
            entry = _edge_entry(sc["map"], e["at"])
            out.append({"op": "spawn", "actor": e["id"], "sprite": e.get("sprite", e["kind"]), "at": entry,
                        "facing": "up", "name": e.get("name", e["kind"])})
            on_stage[e["id"]] = {"at": entry, "down": False}
        if on_stage[e["id"]]["at"] != list(e["at"][:2]):
            walkers.append({"op": "move", "actor": e["id"], "speed": 5, "_from": on_stage[e["id"]]["at"],
                            "path": walk_path(sc["map"], on_stage[e["id"]]["at"], e["at"], _others(on_stage, e["id"])),
                            "wait": False})
            on_stage[e["id"]]["at"] = list(e["at"][:2])
    if walkers:
        longest = max(walkers, key=_path_len)
        walkers.remove(longest)
        for w in walkers:
            w["wait"] = False
        longest["wait"] = True
        walkers.append(longest)
        for w in walkers:
            w.pop("_from", None)
    out += walkers

    # 2. The fight, with the writer's narration after the numbered actions.
    by_after: dict[int, list[str]] = {}
    for nr in narration:
        by_after.setdefault(int(nr["after"]), []).append(nr["text"])
    n_actions = sum(1 for c in battle["cues"] if c["op"] in ("battle_attack", "battle_cast"))
    for k in by_after:
        if k > n_actions:
            problems.append(f"{eid}: narration after action {k}, but the fight has only {n_actions}")

    def flush(lines):
        for text in lines:
            out.extend({"op": "narrate", "text": t} for t in split_box(text))

    count, pending = 0, []
    for c in battle["cues"]:
        if c["op"] in ("battle_turn", "battle_attack", "battle_cast", "battle_end") and pending:
            flush(pending)
            pending = []
        out.append(c)
        if c["op"] == "initiative":
            flush(by_after.pop(0, []))
        if c["op"] in ("battle_attack", "battle_cast"):
            count += 1
            pending = by_after.pop(count, [])
    flush(pending)

    # 3. Who is still standing where.
    for cid, st in battle["end_state"].items():
        if st["dead"] and cid in on_stage:
            on_stage.pop(cid)
        elif cid in on_stage:
            on_stage[cid] = {"at": st["pos"], "down": st["down"]}
    return out
