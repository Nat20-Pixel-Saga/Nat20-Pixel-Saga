"""What each party member remembers: the material for callbacks.

Built from the episode archive (what was shown on screen) before the episode being
written: the wiki's notes on each character, their bond moments, their lines, the
fights (critical hits, who they brought down, when they went down and got back up),
natural 20s and 1s on checks, and the levels they reached and what came with them.
The writer turns one or two of these into a line ("like the wolves at the Birches"),
so characters remember what happened to them (prompts/writer.md, "Callbacks and growth").
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

PARTY = ("brannoc", "ilsevel", "tamsin", "oriel")
PER_CHARACTER = 22          # most recent items kept per character


def _kind(name: str) -> str:
    return re.sub(r"\s*\d+$", "", name).strip()


def _fight_items(record: dict, cid: str) -> list[str]:
    out = []
    for enc in record.get("encounters", []):
        names = {c["id"]: c["name"] for c in enc.get("combatants", [])}
        where = "in the fight" if enc.get("name") in (None, record.get("title")) else f"in the fight ({enc['name']})"
        ev = enc.get("events", [])
        kills = Counter(_kind(names.get(e["actor"], e["actor"])) for e in ev if e["t"] == "death" and e.get("cause") == cid)
        if kills:
            out.append(f"{where}, brought down " + ", ".join(f"{n} {k.lower()}{'s' if n > 1 else ''}"
                                                            for k, n in kills.items()))
        for e in ev:
            if e["t"] == "attack" and e.get("actor") == cid and e.get("critical"):
                out.append(f"{where}, a critical hit on a {_kind(names.get(e['target'], e['target'])).lower()}")
        downs = [e for e in ev if e["t"] == "down" and e.get("actor") == cid]
        if downs:
            last_hit = None
            for e in ev:
                if e["t"] == "attack" and e.get("target") == cid and e.get("hit"):
                    last_hit = e
                if e["t"] == "down" and e.get("actor") == cid:
                    break
            by = f" ({_kind(names.get(last_hit['actor'], last_hit['actor'])).lower()})" if last_hit else ""
            out.append(f"{where}, went down{by}" + (", and made death saves" if any(
                e["t"] == "death_save" and e.get("actor") == cid for e in ev) else ""))
        reacts = Counter(str(e.get("reaction") or e.get("spell") or "reaction").replace("_", " ").title()
                         for e in ev if e["t"] == "reaction" and e.get("actor") == cid)
        for what, n in reacts.items():
            out.append(f"{where}, turned a blow aside with {what}" + (f" ({n} times)" if n > 1 else ""))
    return out


def collect(archive: list[dict], world: dict | None = None, before: str | None = None) -> dict[str, list[str]]:
    """``{character id: ["C01-E004 Wolves at the Birches: ...", ...]}``, oldest first."""
    mem: dict[str, list[str]] = {c: [] for c in PARTY}
    for e in archive:
        if before and e["id"] >= before:
            continue
        rec, facts = e.get("record") or {}, e.get("facts") or {}
        tag = f"{e['id']} {rec.get('title', '')}".strip()
        outcomes = {}
        d = e.get("dir")
        if d and (Path(d) / "outcomes.json").exists():
            outcomes = json.loads((Path(d) / "outcomes.json").read_text())
        for cid in PARTY:
            items = [f"{tag}: {n}" for n in facts.get("character_notes", {}).get(cid, [])]
            items += [f"{tag}: {x}" for x in _fight_items(rec, cid)]
            for ch in outcomes.get("checks", []):
                if ch.get("who") == cid and ch.get("note") in ("natural 20", "natural 1"):
                    items.append(f"{tag}: {ch['note']} on {ch['what'].split(' - ')[-1]}"
                                 + (f" ({ch['means']})" if ch.get("means") else ""))
            for lu in rec.get("level_ups", []):
                if lu.get("id") == cid:
                    items.append(f"{tag}: grew stronger (level {lu['to']}): " + ", ".join(lu.get("new") or lu["gains"]))
            quotes = [q["text"] for q in facts.get("quotes", []) if q.get("speaker") == cid]
            if quotes:
                items.append(f"{tag}: said \"{quotes[0]}\"")
            mem[cid] += items
    for b in (world or {}).get("party", {}).get("bonds", []):
        for note in b.get("notes", []):
            m = re.match(r"^(C\d\d-E\d\d\d): (.*)$", note)
            if not m or (before and m.group(1) >= before):
                continue
            for cid, other in ((b["a"], b["b"]), (b["b"], b["a"])):
                if cid in mem:
                    mem[cid].append(f"{m.group(1)}: with {other.title()}: {m.group(2)}")
    out = {}
    for cid, items in mem.items():
        uniq = list(dict.fromkeys(items))
        uniq.sort(key=lambda x: x[:8])                 # by episode id, stable within an episode
        out[cid] = uniq[-PER_CHARACTER:]
    return out


def as_text(mem: dict[str, list[str]], names: dict[str, str] | None = None) -> str:
    if not any(mem.values()):
        return "(nothing yet: this is the first episode)"
    out = []
    for cid, items in mem.items():
        if not items:
            continue
        out.append(f"{(names or {}).get(cid, cid.title())}:")
        out += [f"- {x}" for x in items]
    return "\n".join(out)
