"""Continuity: mechanical checks first, then a model review.

The mechanical pass is free and catches what a model is bad at noticing:
schema errors, unknown ids, every check and fight placed exactly once, box
lengths, the 2-boxes-per-speaker rule, banned phrases and slang, numbers in
narration right after a roll, spoiler phrases, and the episode ending on a
party member's line. The model review (Haiku 4.5) then reads for meaning:
does the script contradict a roll, break a voice, or leak a secret?
"""
from __future__ import annotations

import re

from ..schema import validate_named
from .assemble import MAX_BOX, assemble
from .context import spoiler_hits
from .resolve import PARTY, Resolution

BANNED = [  # bible 08 §3, plus the slang list in §2.3
    "little did they know", "a chill ran down", "it's quiet. too quiet", "let's do this", "and so, the adventure began",
    "devastating", "menacing",
]
SLANG = ["okay", "cool", "no way", "literally", "awesome", "guys"]
GAME_WORDS = ["dice", "d20", "roll a", "hit points", "saving throw", "initiative", "armor class", "experience points"]


def mechanical(plan: dict, script: dict, res: Resolution, check_cues: dict, sheets: dict) -> list[dict]:
    issues: list[dict] = []

    def add(sev, where, problem, fix=""):
        issues.append({"severity": sev, "where": where, "problem": problem, **({"fix": fix} if fix else {})})

    for e in validate_named(script, "script"):
        add("blocker", "schema", e)
    if issues:
        return issues
    asm = assemble(plan, script, res, check_cues, sheets)
    for p in asm.problems:
        add("blocker", p.split(":")[0], p)
    # Every on-screen check, aftermath roll and encounter placed exactly once.
    wanted = [ch["id"] for sc in plan["scenes"] for ch in sc.get("checks", []) if not ch.get("offscreen")]
    wanted += [a["id"] for a in res.outcomes.get("aftermath", [])]
    wanted += [sc["encounter"]["id"] for sc in plan["scenes"] if sc.get("encounter")]
    for wid in wanted:
        n = asm.placed.get(wid, 0)
        if n != 1:
            add("blocker", wid, f"{wid} is placed {n} times (must be exactly once)",
                f"add one {{op: check/encounter, id: {wid}}} where it happens")
    plan_ids = [s["id"] for s in plan["scenes"]]
    if [s["id"] for s in script["scenes"]] != plan_ids:
        add("blocker", "scenes", f"script scenes must be {plan_ids} in that order")

    camp = int(plan["episode_id"][1:3])
    last_say = None
    for sc in script["scenes"]:
        run_speaker, run = None, 0
        after_roll = False
        for k, c in enumerate(sc["cues"]):
            where = f"{sc['id']}#{k}"
            text = c.get("text", "")
            if c["op"] in ("say", "narrate"):
                if len(text) > MAX_BOX:
                    add("warning", where, f"{len(text)} characters (max {MAX_BOX}); the assembler split it",
                        "split it into two boxes")
                low = text.lower()
                for b in BANNED:
                    if b in low:
                        add("blocker", where, f"banned phrase: {b!r}")
                for s in SLANG:
                    if re.search(rf"\b{re.escape(s)}\b", low):
                        add("blocker", where, f"modern slang: {s!r}")
                for g in GAME_WORDS:
                    if re.search(rf"\b{re.escape(g)}\b", low):
                        add("blocker", where, f"fourth-wall/game word: {g!r}")
                if low.count("suddenly") > 0:
                    add("warning", where, "'suddenly' (allowed once per episode)")
                for hit in spoiler_hits(text, camp):
                    add("blocker", where, f"spoiler: {hit['phrase']!r} ({hit['secret']}) before campaign "
                                          f"{hit['reveal_campaign']}")
                if c["op"] == "narrate" and after_roll and re.search(r"\b\d+\b", text):
                    add("blocker", where, "the narrator states a number right after a roll",
                        "describe the result; the overlay shows the number")
                speaker = c.get("speaker") if c["op"] == "say" else "_narrator"
                run = run + 1 if speaker == run_speaker else 1
                run_speaker = speaker
                if run > 2 and speaker != "_narrator":
                    add("warning", where, f"{speaker} has {run} boxes in a row (max 2)")
                last_say = c.get("speaker") if c["op"] == "say" else "_narrator"
                after_roll = False
            elif c["op"] in ("check", "encounter"):
                after_roll = c["op"] == "check"
                run_speaker, run = None, 0  # a roll or a fight breaks a run of boxes
            elif c["op"] in ("move", "face", "emote", "camera", "wait", "sfx", "music", "music_stop",
                             "lantern", "time_of_day", "spawn", "despawn", "location_card"):
                pass
            else:
                after_roll = False
        for nr in sc.get("battle_narration", []):
            for hit in spoiler_hits(nr["text"], camp):
                add("blocker", f"{sc['id']}~{nr['after']}", f"spoiler: {hit['phrase']!r}")
            if len(nr["text"]) > MAX_BOX:
                add("warning", f"{sc['id']}~{nr['after']}", "narration over 140 characters")
    if last_say not in PARTY:
        add("blocker", "end", "the episode must end on a party member's line (bible 08 §2.7)")
    if not script.get("next_time"):
        add("warning", "end", "missing next_time")
    elif len(script["next_time"]) > 60:
        add("warning", "end", "next_time over 60 characters")
    return issues


def merge(mech: list[dict], review: dict | None, episode_id: str) -> dict:
    issues = list(mech) + list((review or {}).get("issues", []))
    ok = not any(i["severity"] == "blocker" for i in issues)
    return {"schema": "pqc/continuity@1", "episode_id": episode_id, "ok": ok, "issues": issues}


def format_issues(issues: list[dict]) -> str:
    if not issues:
        return "(none)"
    return "\n".join(f"- [{i['severity']}] {i['where']}: {i['problem']}" + (f" -> {i['fix']}" if i.get("fix") else "")
                     for i in issues)
