"""The public wiki (MkDocs, published to GitHub Pages).

Pages are rebuilt from scratch after every episode from three sources only:

1. the episode archive (``episodes/<id>/``): the engine's record (every roll),
   the wiki facts extracted from the final script, and the packaging chapters;
2. the public parts of the state (levels, HP, bonds, lanterns, quests);
3. ``wiki/data/public/characters.json`` (human-approved, spoiler-free intros).

Nothing from the bible or the dossiers is copied, and every page is checked
against ``bible/spoilers.json`` before the build is accepted. The same canon
(``build_canon``) is what the planner and writer read as "what viewers know".
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ..state import ROOT, load_json
from .context import MONTHS, spoiler_hits

EPISODES = ROOT / "episodes"
WIKI = ROOT / "wiki"
DOCS = WIKI / "docs"
PARTY = ("brannoc", "ilsevel", "tamsin", "oriel")


class SpoilerLeak(RuntimeError):
    pass


# ------------------------------------------------------------------ archive
def load_archive() -> list[dict]:
    out = []
    if not EPISODES.exists():
        return out
    for d in sorted(p for p in EPISODES.iterdir() if p.is_dir() and re.match(r"C\d\d-E\d\d\d$", p.name)):
        if not (d / "episode.json").exists():
            continue
        e = {"id": d.name, "record": load_json(d / "episode.json"), "dir": d}
        for key, fname in (("facts", "wiki_facts.json"), ("packaging", "packaging.json"), ("script", "script.json"),
                           ("plan", "plan.json"), ("chapters", "chapters.json")):
            e[key] = load_json(d / fname) if (d / fname).exists() else None
        out.append(e)
    return out


def build_canon(archive: list[dict]) -> dict[str, dict]:
    """Merge every episode's NPC and place facts into one entry per id."""
    canon: dict[str, dict] = {}
    for e in archive:
        f = e.get("facts")
        if not f:
            continue
        for kind, items in (("npc", f.get("npcs", [])), ("place", f.get("places", []))):
            for it in items:
                c = canon.setdefault(it["id"], {"id": it["id"], "kind": kind, "name": it["name"], "first_seen": e["id"],
                                                "appearances": [], "history": []})
                c["name"] = it["name"]
                c["description"] = it["description"]
                for k in ("status", "attitude", "want", "voice"):
                    if it.get(k):
                        c[k] = it[k]
                if e["id"] not in c["appearances"]:
                    c["appearances"].append(e["id"])
                c["history"].append({"episode": e["id"], "description": it["description"]})
        for q in f.get("quotes", []):
            sid = q["speaker"]
            nid = sid if sid.startswith("npc.") else "npc." + sid.replace("_", "-")
            if nid in canon:
                canon[nid].setdefault("quotes", []).append({**q, "episode": e["id"]})
    return canon


# ------------------------------------------------------------------ helpers
def _slug(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", x.lower().split(".", 1)[-1]).strip("-")


def _ep_title(e: dict) -> str:
    c, n = int(e["id"][1:3]), int(e["id"][-3:])
    return f"C{c}E{n} - {e['record'].get('title', '')}"


def _date(clock: dict) -> str:
    return f"{clock['day']} {MONTHS[clock['month'] - 1]} {clock['year']} AK"


def _speaker_name(sid: str, sheets: dict, canon: dict) -> str:
    if sid in sheets:
        return sheets[sid]["name"].split()[0]
    nid = sid if sid.startswith("npc.") else "npc." + sid.replace("_", "-")
    if nid in canon:
        return canon[nid]["name"]
    return sid.replace("_", " ").title()


def _link_npc(nid: str, canon: dict, depth: int = 1) -> str:
    up = "../" * depth
    if nid in canon:
        return f"[{canon[nid]['name']}]({up}{'npcs' if canon[nid]['kind'] == 'npc' else 'places'}/{_slug(nid)}.md)"
    return nid


def _display_names(record: dict, sheets: dict) -> dict[str, str]:
    names = {cid: s["name"].split()[0] for cid, s in sheets.items()}
    for enc in record["encounters"]:
        for c in enc["combatants"]:
            if c["id"] not in names:
                num = re.search(r"-(\d+)$", c["id"])
                names[c["id"]] = c["name"] + (f" {num.group(1)}" if num else "")
    return names


def _roll_rows(record: dict, shown: set[str], names: dict[str, str]) -> list[str]:
    rows = ["| Roll | Who | For | Dice | Total | Against | Result |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in record["rolls"]:
        if shown and r["id"] not in shown:
            continue
        who = names.get(r.get("actor") or "", (r.get("actor") or "").replace("-", " ").title())
        purpose = r["purpose"].split(":", 1)[-1].strip()[:70]
        dice = f"{r['notation']} [{', '.join(map(str, r['rolls']))}]"
        if r.get("advantage") and r["advantage"] != "none":
            dice += f" ({r['advantage']})"
        mod = f" {'+' if r['modifier'] >= 0 else '-'} {abs(r['modifier'])}" if r.get("modifier") else ""
        res = "" if r.get("success") is None else ("success" if r["success"] else "fail")
        if r.get("critical"):
            res += " (critical)"
        rows.append(f"| `{r['id']}` | {who} | {purpose} | {dice}{mod} | **{r['total']}** | "
                    f"{r['dc'] if r.get('dc') is not None else ''} | {res} |")
    return rows


# ------------------------------------------------------------------- pages
def public_cut(now=None) -> tuple[list[dict], Path, tuple[str, object] | None]:
    """What the public wiki may show right now: the episodes whose premiere has passed
    (production/schedule.json), the state after the last of them, and the next premiere."""
    from .. import schedule
    from ..state import GENESIS_DIR
    archive = load_archive()
    shown = [e for e in archive if schedule.is_public(e["id"], now)]
    state_dir = (EPISODES / shown[-1]["id"] / "state_after") if shown else GENESIS_DIR
    nxt = next((e for e in archive if not schedule.is_public(e["id"], now)), None)
    upcoming = (nxt["id"], schedule.premiere(nxt["id"])) if nxt else None
    return shown, state_dir, upcoming


def build_site(docs: Path = DOCS, state_dir: Path = ROOT / "state", check_spoilers: bool = True,
               public_only: bool | None = None, now=None) -> list[Path]:
    """Write the wiki pages. The public site (the default `docs`) only shows episodes that have
    premiered, and the world as it stood after the last of them; previews show everything."""
    if public_only is None:
        public_only = Path(docs) == DOCS
    archive = load_archive()
    upcoming = None
    if public_only:
        archive, state_dir, upcoming = public_cut(now)
    canon = build_canon(archive)
    world = load_json(state_dir / "world.json")
    sheets = {p.stem: load_json(p) for p in sorted((state_dir / "party").glob("*.json"))}
    public = load_json(WIKI / "data" / "public" / "characters.json")["characters"]
    campaign = max([e["record"]["campaign"] for e in archive] or [1])
    pages: dict[str, str] = {}

    # Home
    latest = archive[-1] if archive else None
    site = load_json(WIKI / "data" / "site.json") if (WIKI / "data" / "site.json").exists() else {}
    home = ["# Nat 20 Pixels Saga", "",
            "A pixel-art fantasy story played by 5e rules, one episode every weekday. Four strangers, one road of "
            "lanterns, level 1 to level 20. **Every roll you see on screen is real**: the dice are seeded and logged, "
            "and you can check any of them on the [Dice](dice.md) page.", ""]
    if site.get("youtube"):
        home += [f"**Watch on YouTube: [{site.get('youtube_handle', 'the channel')}]({site['youtube']})**", ""]
    if upcoming:
        from .. import schedule
        uid, when = upcoming
        n = int(uid[-3:])
        label = schedule.local_label(when)
        home += [f"!!! info \"{'First episode' if not latest else 'Next episode'}\"",
                 f"    **Episode {n}** premieres on YouTube on **{label}**." +
                 (f" Watch it on [{site.get('youtube_handle', 'YouTube')}]({site['youtube']})." if site.get("youtube") else ""),
                 ""]
    if latest:
        home += [f"## Latest episode: [{_ep_title(latest)}](episodes/{latest['id'].lower()}.md)", "",
                 latest["facts"]["summary"] if latest.get("facts") else "", ""]
    home += ["## The party", ""]
    for cid in PARTY:
        s = sheets[cid]
        home.append(f"- **[{s['name']}](characters/{cid}.md)** - {public[cid]['title']}. Level {s['level']} "
                    f"{s['species']} {s['class']}.")
    home += ["", f"*In-world date: {_date(world['clock'])}. Episodes so far: {len(archive)}.*", ""]
    pages["index.md"] = "\n".join(home)

    # Episodes
    ep_index = ["# Episodes", "", "| Episode | Summary |", "| --- | --- |"]
    for e in archive:
        f = e.get("facts") or {}
        ep_index.append(f"| [{_ep_title(e)}]({e['id'].lower()}.md) | {f.get('summary', '')} |")
        pages[f"episodes/{e['id'].lower()}.md"] = _episode_page(e, canon, sheets)
    pages["episodes/index.md"] = "\n".join(ep_index)

    # Characters
    notes: dict[str, list[tuple[str, str]]] = {c: [] for c in PARTY}
    quotes_by: dict[str, list[tuple[str, str]]] = {}
    for e in archive:
        f = e.get("facts") or {}
        for cid, items in (f.get("character_notes") or {}).items():
            notes.setdefault(cid, []).extend((e["id"], x) for x in items)
        for q in f.get("quotes", []):
            quotes_by.setdefault(q["speaker"], []).append((e["id"], q["text"]))
    ch_index = ["# The party", ""]
    for cid in PARTY:
        s = sheets[cid]
        ch_index.append(f"- **[{s['name']}]({cid}.md)** - {public[cid]['intro']}")
        pages[f"characters/{cid}.md"] = _character_page(cid, s, public[cid], notes.get(cid, []),
                                                         quotes_by.get(cid, []), world, sheets, archive)
    pages["characters/index.md"] = "\n".join(ch_index)

    # NPCs and places
    npc_index, place_index = ["# People", ""], ["# Places", ""]
    for cid, c in sorted(canon.items(), key=lambda kv: kv[1]["name"]):
        folder = "npcs" if c["kind"] == "npc" else "places"
        (npc_index if c["kind"] == "npc" else place_index).append(
            f"- **[{c['name']}]({_slug(cid)}.md)** - {c['description']}")
        pages[f"{folder}/{_slug(cid)}.md"] = _canon_page(c, quotes_by)
    pages["npcs/index.md"] = "\n".join(npc_index)
    pages["places/index.md"] = "\n".join(place_index)

    # Quotes
    q = ["# Quotes", "", "Memorable lines, by episode. The writers reuse them as callbacks.", ""]
    for e in archive:
        for item in (e.get("facts") or {}).get("quotes", []):
            q.append(f"> {item['text']}  \n> - **{_speaker_name(item['speaker'], sheets, canon)}**, "
                     f"[{_ep_title(e)}](episodes/{e['id'].lower()}.md)\n")
    pages["quotes.md"] = "\n".join(q)

    # Lanterns
    status = {"lit": "lit", "flicker": "flickering", "dead": "**dark**"}
    seen = {}
    for e in archive:
        for ch in e["record"]["state_changes"]:
            if ch.get("type") == "lantern" and ch.get("applied"):
                seen[ch["id"]] = e["id"]
    lan = ["# The Lantern Road", "", "The lanterns the story has shown so far, and their state today.", "",
           "| Lantern | State | Changed in |", "| --- | --- | --- |"]
    for lid, st in sorted(world["lanterns"].items()):
        num = lid.split(".")[-1].lstrip("0") or "0"
        changed = seen.get(lid)
        lan.append(f"| No. {num} | {status.get(st, st)} | "
                   f"{f'[{changed}](episodes/{changed.lower()}.md)' if changed else ''} |")
    pages["lanterns.md"] = "\n".join(lan)

    # Quests (public: those that exist; objectives as shown)
    qs = ["# Quests", ""]
    for qd in world.get("quests", []):
        qs += [f"## {qd['title']}", "", f"*Status: {qd['status']}*", ""] + [f"- {o}" for o in qd.get("objectives", [])] + [""]
    pages["quests.md"] = "\n".join(qs)

    # Dice
    dice = ["# Dice", "",
            "Every roll on the show comes from one seeded generator per episode. The seed is "
            "`<episode>-<attempt>` (for example `C01-E001-1`); each die is "
            "`HMAC-SHA256(seed, counter)` reduced to the die's size with rejection sampling, so anyone can "
            "recompute any roll from its seed and counter. Episodes are never re-rolled; a technical rerun would "
            "increase the attempt number and be listed here.", "",
            "```python", "from pqc.dice import Dice", "Dice.verify_log(seed, rolls)   # True if every roll matches",
            "```", "", "| Episode | Seed | Attempt | Rolls | Log |", "| --- | --- | --- | --- | --- |"]
    for e in archive:
        r = e["record"]
        dice.append(f"| [{_ep_title(e)}](episodes/{e['id'].lower()}.md) | `{r['seed']}` | {r['attempt']} | "
                    f"{len(r['rolls'])} | [JSON](rolls/{e['id'].lower()}.json) |")
    pages["dice.md"] = "\n".join(dice)

    pages["about.md"] = _about()

    # Names as known on screen: a sheet's full name (often a secret) is replaced everywhere.
    shown_ids = {e["id"] for e in archive}
    for cid, pub in public.items():
        full = sheets.get(cid, {}).get("name")
        known = pub.get("name") or (full or cid).split()[0]
        for rv in pub.get("revealed", []):
            if rv["episode"] in shown_ids:
                known = rv["name"]
        if full and full != known:
            pages = {k: v.replace(full, known) for k, v in pages.items()}

    # Leak check, then write.
    if check_spoilers:
        leaks = [(name, h["phrase"]) for name, text in pages.items() for h in spoiler_hits(text, campaign)]
        if leaks:
            raise SpoilerLeak(f"Spoilers in wiki pages: {leaks}")
    if docs.exists():
        shutil.rmtree(docs)
    written = []
    for name, text in pages.items():
        path = docs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        written.append(path)
    brand_dir = ROOT / "assets" / "brand"          # logo and favicon for the theme (mkdocs.yml)
    if (brand_dir / "logo_mark.png").exists():
        from PIL import Image
        (docs / "assets").mkdir(parents=True, exist_ok=True)
        mark = Image.open(brand_dir / "logo_mark.png")
        mark.resize((96, 96), Image.NEAREST).save(docs / "assets" / "logo.png")
        mark.resize((48, 48), Image.NEAREST).save(docs / "assets" / "favicon.png")
        written += [docs / "assets" / "logo.png", docs / "assets" / "favicon.png"]
    for e in archive:
        path = docs / "rolls" / f"{e['id'].lower()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"seed": e["record"]["seed"], "rolls": e["record"]["rolls"]}, indent=1))
        written.append(path)
    return written


def _episode_page(e: dict, canon: dict, sheets: dict) -> str:
    r, f, pk = e["record"], e.get("facts") or {}, e.get("packaging") or {}
    out = [f"# {_ep_title(e)}", "", f"*In-world date: {_date(r['in_world_date'])}*  ", f"*Seed: `{r['seed']}`*", ""]
    site = WIKI / "data" / "site.json"
    repo = load_json(site).get("repo") if site.exists() else None
    yt = load_json(WIKI / "data" / "youtube.json").get(e["id"], {}) if (WIKI / "data" / "youtube.json").exists() else {}
    if yt.get("linked"):              # premiere has passed (scripts/youtube_upload.py link)
        out += [f"[Watch on YouTube]({yt['url']})", ""]
    elif pk.get("youtube_url"):
        out += [f"[Watch on YouTube]({pk['youtube_url']})", ""]
    if repo:
        out += [f"[Download the episode video](https://github.com/{repo}/releases/tag/{e['id']})", ""]
    elif pk.get("video_url"):
        out += [f"[Watch the episode]({pk['video_url']})", ""]
    out += ["## Summary", "", f.get("summary", ""), ""]
    if f.get("events"):
        out += ["## What happened", ""] + [f"- {x}" for x in f["events"]] + [""]
    if e.get("chapters"):
        out += ["## Chapters", ""] + [f"- `{c['time']}` {c['title']}" for c in e["chapters"]] + [""]
    shown = set()
    for ch in r["checks"]:
        if not ch.get("offscreen"):
            shown.add(ch["roll"])
    out += ["## Rolls on screen", ""]
    for ch in r["checks"]:
        if ch.get("offscreen"):
            continue
        roll = next(x for x in r["rolls"] if x["id"] == ch["roll"])
        who = sheets.get(ch["actor"], {}).get("name", ch["actor"]).split()[0]
        what = (ch.get("skill") or ch.get("ability") or "").replace("_", " ").title()
        out.append(f"- **{who} - {what}** (DC {ch['dc']}): rolled {roll['natural']} {'+' if roll['modifier'] >= 0 else '-'} "
                   f"{abs(roll['modifier'])} = **{roll['total']}** - {'success' if ch['success'] else 'failure'} "
                   f"(`{roll['id']}`)")
    out.append("")
    for enc in r["encounters"]:
        ini = next((x for x in enc["events"] if x["t"] == "initiative_order"), None)
        downs = [x for x in enc["events"] if x["t"] == "down"]
        out += [f"## Fight: {enc['name']}", "",
                f"- **Result:** {'victory' if enc['winner'] == 'party' else 'defeat'} in {enc['rounds']} rounds, "
                f"{enc.get('xp', 0)} XP", ""]
        if ini:
            names = {c["id"]: c["name"] for c in enc["combatants"]}
            out.append("- **Initiative:** " + ", ".join(names.get(i, i) for i in ini["order"]))
        if downs:
            names = {c["id"]: c["name"] for c in enc["combatants"]}
            out.append("- **Went down:** " + ", ".join(names.get(x["actor"], x["actor"]) for x in downs))
        attacks = [x for x in enc["events"] if x["t"] == "attack" and not x.get("blocked")]
        hits = sum(1 for x in attacks if x["hit"])
        out += [f"- **Attacks:** {len(attacks)}, {hits} hits", ""]
    out += ["<details><summary>Full roll log</summary>", ""] + _roll_rows(r, set(), _display_names(r, sheets)) + \
        ["", "</details>", ""]
    if f.get("quotes"):
        out += ["## Quotes", ""]
        for q in f["quotes"]:
            out.append(f"> {q['text']}  \n> - **{_speaker_name(q['speaker'], sheets, canon)}**\n")
    met = [n["id"] for n in f.get("npcs", [])] + [p["id"] for p in f.get("places", [])]
    if met:
        out += ["## People and places", "", ", ".join(_link_npc(m, canon) for m in met), ""]
    return "\n".join(out)


def _character_page(cid, s, pub, notes, quotes, world, sheets, archive) -> str:
    from ..state import character_from_sheet
    c = character_from_sheet(s)
    out = [f"# {s['name']}", "", f"*{pub['title']}*", "", pub["intro"], "",
           "| | |", "| --- | --- |",
           f"| **Species / class** | {s['species'].title()} {s['class'].title()}"
           + (f" ({s['subclass'].title()})" if s.get("subclass") else "") + " |",
           f"| **Level** | {s['level']} |", f"| **Hit points** | {s['hp']['current']} / {s['hp']['max']} |",
           f"| **Armour class** | {c.ac} |", ""]
    if notes:
        out += ["## What we know", ""] + [f"- {txt} *({eid})*" for eid, txt in notes] + [""]
    bonds = [b for b in world["party"]["bonds"] if cid in (b["a"], b["b"])]
    if bonds:
        out += ["## Bonds", "", "| With | Trust | Tension |", "| --- | --- | --- |"]
        for b in bonds:
            other = b["b"] if b["a"] == cid else b["a"]
            out.append(f"| [{sheets[other]['name'].split()[0]}]({other}.md) | {'●' * b['trust'] or '-'} | "
                       f"{'●' * b['tension'] or '-'} |")
        out.append("")
    if quotes:
        out += ["## In their own words", ""] + [f"> {t}  \n> - *{eid}*\n" for eid, t in quotes[-8:]]
    eps = [e["id"] for e in archive]
    if eps:
        out += ["## Episodes", "", ", ".join(f"[{x}](../episodes/{x.lower()}.md)" for x in eps), ""]
    return "\n".join(out)


def _canon_page(c: dict, quotes_by: dict) -> str:
    out = [f"# {c['name']}", "", c["description"], ""]
    facts = [(k, c[k]) for k in ("status", "attitude", "want", "voice") if c.get(k)]
    if facts:
        out += ["| | |", "| --- | --- |"] + [f"| **{k.title()}** | {v} |" for k, v in facts] + [""]
    out += [f"*First seen: [{c['first_seen']}](../episodes/{c['first_seen'].lower()}.md)*", ""]
    if len(c["history"]) > 1:
        out += ["## Over time", ""] + [f"- *{h['episode']}*: {h['description']}" for h in c["history"]] + [""]
    sid = c["id"].split(".", 1)[-1].replace("-", "_")
    qs = c.get("quotes") or [{"text": t, "episode": e} for e, t in quotes_by.get(sid, [])]
    if qs:
        out += ["## Quotes", ""] + [f"> {q['text']}  \n> - *{q['episode']}*\n" for q in qs]
    return "\n".join(out)


def _about() -> str:
    credits = (ROOT / "assets" / "CREDITS.md").read_text(encoding="utf-8")
    footer = credits.split("## Suggested description footer", 1)[-1].strip()
    return "\n".join([
        "# About", "",
        "Nat 20 Pixels Saga is an automated show: a rules engine rolls every die, Claude plans and writes "
        "each episode within a fixed series bible, and a pixel-art renderer turns the result into video. "
        "This wiki is rebuilt after every episode from what was shown on screen.", "",
        "## Credits", "", footer.replace("> ", ""), "",
        "This work includes material from the System Reference Document 5.2 (\"SRD 5.2\") by Wizards of the Coast "
        "LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2 is licensed under the Creative Commons "
        "Attribution 4.0 International License (https://creativecommons.org/licenses/by/4.0/legalcode).", ""])
