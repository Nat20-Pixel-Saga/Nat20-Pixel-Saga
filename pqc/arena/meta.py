"""The Pit, Season 1: YouTube titles, descriptions, pinned comments and the release calendar.

    python scripts/arena_season.py meta      # after the renders: writes the files below into the output folder
                                            # and production/arena/

* ``s1_calendar.json`` / ``.csv``: every upload in order (videos, trailer Shorts, highlight Shorts).
* ``s1_youtube.md``: what to paste for each upload, in calendar order.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

from . import season as SE

ROOT = Path(__file__).resolve().parents[2]
CREDITS = ("Art, music & SFX: Ninja Adventure Asset Pack by Pixel-boy & AAA (CC0). Fonts: Pixelify Sans, Tiny5 (OFL).\n"
           "This work includes material from the System Reference Document 5.2.1 by Wizards of the Coast LLC, "
           "licensed under CC BY 4.0. Not affiliated with Wizards of the Coast.")
PLAYLIST = "The Pit, Season 1: The Bronze Crown"
SCHEDULE = "New fights every Wednesday and Saturday at 18:00 (Paris time)."
STORY = ("From the makers of Nat 20 Pixels, the pixel-art fantasy story played by the same dice engine: "
         "https://www.youtube.com/@Nat20px")
TAGS = ["dnd", "dnd 5e", "d&d", "who would win", "pixel art", "versus", "battle simulation", "dice", "ttrpg",
        "the pit", "nat 20 pixels"]


def _d(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso)


def long_date(d: dt.date) -> str:
    return f"{SE.DAYS[d.weekday()].title()} {d.day} {['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][d.month - 1]} {d.year}"


def names_of(seg: dict) -> tuple[str, str]:
    return seg["a"][0]["name"], seg["b"][0]["name"]


def titles(season: dict, ep: dict, res: dict) -> dict:
    n, kind = ep["n"], ep["kind"]
    tag = f"The Pit #{n}" if not ep.get("bonus") else "The Pit Bonus"
    seg = res["segments"][0]
    if kind == "duel":
        a, b = names_of(seg)
        t = f"{a} vs {b}: Who Wins? (Real D&D Dice, Best of {ep['best_of']}) | {tag}"
        q = f"{a} or {b}?"
    elif kind == "how_many":
        t = f"{ep['title']} (Real D&D Dice) | {tag}"
        q = ep["title"]
    elif kind == "rumble":
        t = f"{ep['title']} | {tag}"
        q = "Who's the last one standing?"
    elif kind == "crown_semis":
        (a1, b1), (a2, b2) = names_of(res["segments"][0]), names_of(res["segments"][1])
        t = f"{a1} vs {b1}, {a2} vs {b2}: Bronze Crown Semifinals | {tag}"
        q = "Who reaches the final?"
    else:
        a, b = names_of(seg)
        t = f"{a} vs {b}: The Bronze Crown Final (Best of 7) | {tag}"
        q = f"{a} or {b}: who wears the first Bronze Crown?"
    return {"title": t[:100], "question": q}


def odds_line(ep: dict, res: dict) -> str:
    seg = res["segments"][0]
    k = ep["kind"]
    if k in ("duel", "crown_final"):
        m = seg["match"]
        a, b = names_of(seg)
        fav, p = (a, m["p_match"]) if m["p_match"] >= 0.5 else (b, 1 - m["p_match"])
        return (f"Before a single real roll, we ran the fight {m['prior_n']:,} times: {fav} takes a best of "
                f"{m['best_of']} {round(p * 100)}% of the time. Then the real dice decide.")
    if k == "crown_semis":
        return "Two best-of-5 semifinals. The winners meet on Saturday in a best of 7."
    if k == "how_many":
        star = seg["star"]["name"]
        pts = ", ".join(f"{c} {ep['plural'].lower()}: {round(seg['ramp'].get(c, 0) * 100)}%" for c in seg["counts"])
        return f"The {star}'s chance to survive each round, from {seg.get('prior_n', 1000):,} simulated fights per round: {pts}."
    if k == "rumble":
        fav = max(seg["fighters"], key=lambda f: seg["prior"].get(f["team"], 0))
        return (f"{len(seg['fighters'])} fighters, everyone against everyone. From {seg.get('prior_n', 1000):,} simulated "
                f"rumbles, the favourite is {fav['name']} at {round(seg['prior'].get(fav['team'], 0) * 100)}%.")
    return ""


def intro(ep: dict, res: dict) -> str:
    k = ep["kind"]
    seg = res["segments"][0]
    if k == "duel":
        a, b = names_of(seg)
        q = "Episode " + str(ep["n"]) + (" decides a place in the Bronze Crown." if ep.get("qualifier") else
                                         " is a heavyweight special: a taste of Season 2.")
        return f"{a} vs {b}, played by the official 5th-edition stat blocks with real, seeded dice. {q}"
    if k == "how_many":
        return (f"One {seg['star']['name']} against {ep['plural'].lower()}: {seg['counts'][0]} of them, then more, round "
                f"after round, until the {seg['star']['name']} falls. Every roll is real.")
    if k == "rumble":
        return f"{ep['title']}. Everyone against everyone, last one standing. Every roll is real."
    if k == "crown_semis":
        return "The Bronze Crown semifinals: four qualifiers, two best-of-5 matches, every roll real."
    return "The Bronze Crown final: best of 7, real dice, one crown."


def description(season: dict, ep: dict, res: dict, chapters: list) -> str:
    t = titles(season, ep, res)
    parts = [intro(ep, res), odds_line(ep, res), f"{t['question']} Call it in the comments before you watch."]
    road = []
    if not ep.get("bonus"):
        road.append("Road to the Bronze Crown: four places, one crown. Semifinals Wednesday 18 November, final "
                    "Saturday 21 November.")
        road.append(SCHEDULE)
        bonus = _bonus(season)
        if bonus and bonus.get("date"):
            road.append(f"Bonus fight after the final, {long_date(_d(bonus['date'])).rsplit(' ', 1)[0]}: how many "
                        "goblins does it take to beat a T-Rex?")
        elif season.get("unlock"):
            road.append(f"{season['unlock']['subscribers']} subscribers unlocks a bonus fight: how many goblins does it "
                        "take to beat a T-Rex?")
    else:
        road.append("A bonus fight to close Season 1. Season 2, the Silver Crown, is next.")
    ch = "Chapters\n" + "\n".join(f"{_fmt(tm)} {label}" for tm, label in chapters) if chapters else ""
    how = (f"How it works: a rules engine plays the SRD 5.2.1 stat blocks. Every roll is seeded and logged "
           f"(this episode's seed: {ep['seed']}), so any fight can be replayed exactly. The win chance on screen "
           f"is a fresh simulation from that exact moment of the fight, replayed hundreds of times.")
    tags = "#dnd #whowouldwin #pixelart"
    return "\n\n".join(p for p in [" ".join(parts), "\n".join(road), ch, how, STORY, CREDITS, tags] if p)


def _fmt(t: float) -> str:
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


def pinned(season: dict, ep: dict, res: dict, nxt: dict | None, nres: dict | None) -> str:
    seg = res["segments"][0]
    k = ep["kind"]
    if k in ("duel", "crown_final"):
        a, b = names_of(seg)
        first = f"Who did you pick before the dice rolled: {a} or {b}? Reply and be honest."
    elif k == "how_many":
        first = f"What was your guess? Reply with the number of {ep['plural'].lower()} you thought it would take."
    elif k == "rumble":
        first = "Who was your pick? Reply with the name."
    else:
        first = "Who did you have in the final?"
    if nxt:
        nt = nxt["title"] if nxt["kind"] not in ("crown_semis", "crown_final") else titles(season, nxt, nres)["title"].split(" | ")[0]
        stop = "" if nt.endswith(("?", "!", ".")) else "."
        second = f"Next in the Pit, {SE.DAYS[_d(nxt['date']).weekday()].title()}: {nt}{stop} Subscribe so you don't miss it."
    elif ep.get("bonus"):
        second = "Season 2: the Silver Crown. Nominate a fighter below; the most-liked nominations get in."
    else:
        second = ("Season 2: the Silver Crown, CR 2 and 3. Nominate a fighter below; the most-liked nominations get in. "
                  f"And at {season['unlock']['subscribers']} subscribers the T-Rex bonus goes up.")
    return f"{first}\n\n{second}"


def _bonus(season: dict) -> dict | None:
    return next((e for e in season["episodes"] if e.get("bonus")), None)


def short_texts(season: dict, ep: dict, res: dict, which: str, info: dict | None) -> tuple[str, str]:
    t = titles(season, ep, res)
    base = t["title"].split(" | ")[0].split(":")[0]
    if ep["kind"] in ("crown_semis", "crown_final"):
        base = "The Bronze Crown " + ("semifinals" if ep["kind"] == "crown_semis" else "final")
    if which == "trailer":
        title = f"{base}: who wins? Full fight tomorrow | The Pit"
        if ep["kind"] == "how_many":
            title = f"{ep['title']} Full fight tomorrow | The Pit"
        desc = (f"{t['question']} Comment your pick now: the full fight premieres tomorrow at 18:00 (Paris time).\n\n"
                "Real D&D 5e stat blocks, real seeded dice, no rerolls.\n\n" + CREDITS)
    else:
        hook = (info or {}).get("hook") or "Every roll is real"
        small = {"a", "to", "of", "the", "in", "on", "vs", "it"}
        words = hook.lower().split()
        nice = " ".join(w if (i and w in small and i != len(words) - 1) else w[:1].upper() + w[1:]
                        for i, w in enumerate(words))
        title = f"{nice} | {base}"
        desc = (f"{base}: the full fight is on the channel (tap the link above).\n"
                "Real D&D 5e stat blocks, real seeded dice, no rerolls.\n\n" + CREDITS)
    return title[:100], desc


def calendar(season: dict) -> list[dict]:
    out = []
    vt = season["video_time"]
    for ep in season["episodes"]:
        if ep.get("bonus") and not ep.get("date"):
            continue                    # an undated bonus waits (plan() lists it without times)
        d = _d(ep["date"])
        stem = f"pit-s1e{ep['n']:02d}"
        out.append({"when": f"{d - dt.timedelta(days=1)} {season['short_time']}", "kind": "trailer short", "episode": ep["n"],
                    "file": f"{stem}-trailer-short.mp4"})
        out.append({"when": f"{d} {vt}", "kind": "video", "episode": ep["n"], "file": f"{stem}.mp4",
                    "thumbnail": f"{stem}-thumbnail.png"})
        out.append({"when": f"{d + dt.timedelta(days=1)} 18:00", "kind": "highlight short A", "episode": ep["n"],
                    "file": f"{stem}-short-a.mp4"})
        b_time = "11:00" if d.weekday() == 2 else "18:00"     # Wed videos: Friday morning, before Saturday's trailer
        out.append({"when": f"{d + dt.timedelta(days=2)} {b_time}", "kind": "highlight short B", "episode": ep["n"],
                    "file": f"{stem}-short-b.mp4"})
    out.sort(key=lambda r: r["when"])
    return out


def plan(season: dict, out_root: Path, arena) -> list[dict]:
    """Every upload with everything to paste: the data behind s1_youtube.md and the control-room page."""
    res = {e["n"]: SE.resolve(season, e["n"], arena, out_root, full=False) for e in season["episodes"]}
    full = {}
    for e in season["episodes"]:
        p = out_root / f"E{e['n']:02d}" / "result.json"
        full[e["n"]] = SE.load_result(p) if p.exists() else res[e["n"]]
    eps = {e["n"]: e for e in season["episodes"]}
    shorts_info = {}
    marks = {}
    for e in season["episodes"]:
        d = out_root / f"E{e['n']:02d}"
        p = d / "shorts.json"
        shorts_info[e["n"]] = json.loads(p.read_text()) if p.exists() else {}
        mp = d / f"pit-s1e{e['n']:02d}.marks.json"
        marks[e["n"]] = json.loads(mp.read_text()) if mp.exists() else {"chapters": [], "duration_s": None}
    fmt = {"duel": "duel", "how_many": "how many", "rumble": "rumble", "crown_semis": "crown", "crown_final": "crown"}
    rows = []
    cal = calendar(season)
    b = next((e for e in season["episodes"] if e.get("bonus")), None)
    if b and not b.get("date"):
        stem = f"pit-s1e{b['n']:02d}"
        cal += [{"when": None, "kind": k, "episode": b["n"], "file": f, **({"thumbnail": f"{stem}-thumbnail.png"} if k == "video" else {})}
                for k, f in (("trailer short", f"{stem}-trailer-short.mp4"), ("video", f"{stem}.mp4"),
                             ("highlight short A", f"{stem}-short-a.mp4"), ("highlight short B", f"{stem}-short-b.mp4"))]
    for row in cal:
        n = row["episode"]
        ep, r = eps[n], full[n]
        nxt = eps.get(n + 1) if n + 1 in eps and (not eps[n + 1].get("bonus") or eps[n + 1].get("date")) else None
        out = {"id": f"e{n:02d}-" + {"video": "video", "trailer short": "trailer", "highlight short A": "a",
                                       "highlight short B": "b"}[row["kind"]],
               "when": row["when"], "kind": row["kind"], "episode": n, "file": row["file"],
               "format": "bonus" if ep.get("bonus") else fmt[ep["kind"]], "bonus": bool(ep.get("bonus"))}
        if row["kind"] == "video":
            t = titles(season, ep, r)
            out.update(title=t["title"], description=description(season, ep, r, marks[n]["chapters"]),
                       tags=", ".join(TAGS + [x.strip().lower() for x in t["title"].split(" | ")[0].split(":")[0].split(" vs ")[:2]]),
                       pinned=pinned(season, ep, r, nxt, full.get(n + 1)), thumbnail=row.get("thumbnail"),
                       duration=marks[n]["duration_s"])
        else:
            which = {"trailer short": "trailer", "highlight short A": "a", "highlight short B": "b"}[row["kind"]]
            info = shorts_info.get(n, {}).get(which)
            title, desc = short_texts(season, ep, r, which, info)
            out.update(title=title, description=desc, related=f"Episode {n}" if not ep.get("bonus") else "the bonus video",
                       duration=(info or {}).get("duration_s"))
        rows.append(out)
    return rows


def write_all(season: dict, out_root: Path, assets, arena) -> list[Path]:
    rows = plan(season, out_root, arena)
    lines = ["# The Pit, Season 1: upload plan", "",
             f"Channel: {season['channel']}. Playlist: **{PLAYLIST}** (create it once, add every video).",
             "All times are Paris time. Every file is in the GitHub release `pit-s1`.", "",
             "**For each video:** upload the MP4, set the thumbnail, paste title and description, add to the playlist, "
             "schedule it as a premiere at the time below. End screen (last 16 s, the frames are drawn for it): left box = "
             "the previous Pit episode or the playlist, right circle = Subscribe. After it goes public, pin the comment below.",
             "",
             "**For each Short:** upload the MP4, paste title and description, schedule it, and set **Related video** to "
             "its full episode. A trailer goes out the day before its episode: if YouTube doesn't offer the scheduled "
             "premiere yet, link the previous Pit episode and switch the link once the episode is live.", ""]
    bonus_head = False
    for r in rows:
        if r["when"]:
            dd = _d(r["when"].split()[0])
            head = f"{long_date(dd)}, {r['when'].split()[1]}"
        else:
            if not bonus_head:
                lines += [f"## Bonus: when the channel reaches {season['unlock']['subscribers']} subscribers", "",
                          "Ready to go: the trailer Short the day you cross the line, the video the next day at 18:00, "
                          "the two highlight Shorts on the following days.", ""]
                bonus_head = True
            head = "Bonus"
        length = f"  **Length:** {_fmt(r['duration'])}" if r.get("duration") else ""
        if r["kind"] == "video":
            lines += [f"## {head}: Episode {r['episode']} (video)" if r["when"] else "### Bonus video", "",
                      f"**File:** `{r['file']}`  **Thumbnail:** `{r['thumbnail']}`{length}", "",
                      "**Title**", "", "```", r["title"], "```", "", "**Description**", "", "```", r["description"], "```", "",
                      "**Tags**", "", "```", r["tags"], "```", "", "**Pinned comment** (once it's public)", "", "```",
                      r["pinned"], "```", ""]
        else:
            lines += [f"## {head}: Episode {r['episode']} {r['kind']}" if r["when"] else f"### Bonus {r['kind']}", "",
                      f"**File:** `{r['file']}`  **Related video:** {r['related']}{length}", "",
                      "**Title**", "", "```", r["title"], "```", "", "**Description**", "", "```", r["description"], "```", ""]
    out_root.mkdir(parents=True, exist_ok=True)
    md = out_root / "s1_youtube.md"
    md.write_text("\n".join(lines))
    pj = out_root / "s1_plan.json"
    pj.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    cj = out_root / "s1_calendar.json"
    cal = [{k: r[k] for k in ("when", "kind", "episode", "file", "title")} for r in rows]
    cj.write_text(json.dumps(cal, indent=1, ensure_ascii=False))
    cc = out_root / "s1_calendar.csv"
    with cc.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["when (Paris)", "kind", "episode", "file", "title"])
        for r in cal:
            w.writerow([r["when"] or "at 100 subscribers", r["kind"], r["episode"], r["file"], r["title"]])
    return [md, pj, cj, cc]
