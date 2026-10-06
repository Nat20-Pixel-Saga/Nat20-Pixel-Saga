"""The context pack: what each model sees.

Two audiences:

* **DM context** (planner, writer, continuity): the bible *with* its
  ``> SECRET`` blocks, the dossiers, voice sheets and the full state, so the
  story can foreshadow without revealing.
* **Public context** (wiki, packaging): the same material with every secret
  block and secret dossier section removed, so the steps that write things
  viewers will read never see a secret in the first place.

The large, stable part goes in a cached system block; per-episode material
(state, beat, previous summaries) goes in the user message.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .. import features
from ..rules import SKILLS
from ..state import ROOT, load_json

BIBLE = ROOT / "bible"
DOSSIERS = ROOT / "dossiers"
CAMPAIGN_DIR = ROOT / "campaign"

# Bible chapters in the cached core, per audience.
DM_CORE = ["00_series_bible", "01_world_and_cosmology", "06_recurring_npcs", "08_voice_and_style", "10_rules_of_play"]
# Public steps get only what a viewer may know: the everyday world sections of
# chapter 01 and the style guide, both with SECRET blocks removed. The series
# bible (00) states the premise's twists outright, so it is never public.
PUBLIC_CORE = {"01_world_and_cosmology": ("1.", "2.", "3.", "6.", "7.", "8."), "08_voice_and_style": None}
# Dossier sections that may be shown publicly (everything else is DM-only).
PUBLIC_DOSSIER_SECTIONS = ("At a glance",)
DM_DOSSIER_SECTIONS = ("At a glance", "Appearance", "Backstory", "Personality", "Voice sheet", "Hooks", "Secrets",
                       "Relationships at the start", "Growth arc")

_FRONT = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _read(path: Path) -> str:
    return _FRONT.sub("", path.read_text(encoding="utf-8")).strip()


def strip_secrets(md: str) -> str:
    """Remove ``> SECRET ...`` blockquotes (a SECRET line and the quoted lines
    that follow it) and any section headed "Secrets"."""
    out, skipping_quote, skip_level = [], False, None
    for line in md.splitlines():
        heading = re.match(r"^(#+)\s+(.*)", line)
        if heading:
            level = len(heading.group(1))
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if re.match(r"secrets?\b", heading.group(2).strip(), re.I):
                skip_level = level
                continue
        if skip_level is not None:
            continue
        if re.match(r"^>\s*SECRET\b", line):
            skipping_quote = True
            continue
        if skipping_quote:
            if line.startswith(">"):
                continue
            skipping_quote = False
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def sections(md: str, keep: tuple[str, ...]) -> str:
    """Keep only the level-2 sections whose heading starts with one of ``keep``."""
    out, on = [], False
    for line in md.splitlines():
        m = re.match(r"^##\s+(.*)", line)
        if m:
            on = any(m.group(1).strip().lower().startswith(k.lower()) for k in keep)
        elif line.startswith("# "):
            out.append(line)
            continue
        if on:
            out.append(line)
    return "\n".join(out).strip()


def bible_text(chapters, public: bool) -> str:
    parts = []
    for ch in chapters:
        txt = _read(BIBLE / f"{ch}.md")
        keep = chapters[ch] if isinstance(chapters, dict) else None
        if keep:
            txt = sections(txt, keep)
        parts.append(strip_secrets(txt) if public else txt)
    retcons = BIBLE / "RETCONS.md"
    if retcons.exists() and not public:  # production notes: DM steps only
        parts.append(_read(retcons))
    return "\n\n".join(parts)


def dossier_text(public: bool) -> str:
    keep = PUBLIC_DOSSIER_SECTIONS if public else DM_DOSSIER_SECTIONS
    out = []
    for cid in ("brannoc", "ilsevel", "tamsin", "oriel"):
        txt = sections(_read(DOSSIERS / f"{cid}.md"), keep)
        out.append(strip_secrets(txt) if public else txt)
    return "\n\n".join(out)


# ------------------------------------------------------------- compact state
def party_brief(sheets: dict[str, dict], progress: bool = False, supplies: bool = False) -> str:
    """One compact block per character: what a planner needs to set fair DCs.
    ``progress``: XP and XP to the next level; ``supplies``: rations and Exhaustion (production/features.json)."""
    from ..state import character_from_sheet
    lines = []
    for cid, s in sheets.items():
        c = character_from_sheet(s)
        skills = {k: c.skill_bonus(k) for k in sorted(SKILLS)}
        best = sorted(skills.items(), key=lambda kv: -kv[1])[:6]
        sc = s.get("spellcasting") or {}
        slots = {k: v["current"] for k, v in sc.get("slots", {}).items()}
        spells = sc.get("cantrips", []) + sc.get("prepared", sc.get("known", []))
        lines.append(
            f"- {cid}: {s['name']} - L{s['level']} {s['species']} {s['class']}"
            + (f" ({s['subclass']})" if s.get("subclass") else "")
            + f" | HP {s['hp']['current']}/{s['hp']['max']} AC {c.ac} speed {c.speed}"
            + f" | passive Perception {c.passive('perception')}"
            + f" | best skills: " + ", ".join(f"{k} {v:+d}" for k, v in best)
            + (f" | slots {slots} spells: {', '.join(spells)}" if sc else "")
            + (f" | conditions {s['conditions']}" if s.get("conditions") else "")
            + (_progress_note(s) if progress else "")
            + (_supplies_note(s) if supplies else "")
        )
    return "\n".join(lines)


def _progress_note(s: dict) -> str:
    from ..progression import xp_to_next
    togo = xp_to_next(s)
    return f" | XP {s.get('xp', 0)}" + (f" ({togo} to level {s['level'] + 1})" if togo is not None else "")


def _supplies_note(s: dict) -> str:
    rations = sum(i["qty"] for i in s.get("inventory", []) if i["id"] == "rations")
    ex = s.get("exhaustion", 0)
    return f" | rations {rations}" + (f" | Exhaustion {ex}" if ex else "")


def world_brief(world: dict, public: bool = False) -> str:
    clock = world["clock"]
    met = {k: v for k, v in world["npcs"].items()
           if not public or (v.get("status") != "unmet" and v.get("first_seen") and v.get("name_known", True))}
    hooks = [h for h in world.get("hooks", []) if not public or h["status"] != "dormant"]
    return json.dumps({
        "date": f"{clock['day']} {MONTHS[clock['month'] - 1]} {clock['year']} AK, {clock['time_of_day']}",
        "series": world["series"], "location": world["location"],
        "quests": world.get("quests", []), "lanterns": world.get("lanterns", {}),
        "lantern_stars_dark": world.get("lantern_stars_dark", 0),
        "npcs": met, "hooks": hooks, "flags": world.get("flags", {}),
        "bonds": [{k: b[k] for k in ("a", "b", "trust", "tension")} for b in world["party"]["bonds"]],
        "factions": {k: v["reputation"] for k, v in world.get("factions", {}).items()
                     if v.get("known_to_party") or not public},
    }, ensure_ascii=False, separators=(",", ":"))


# bible/01 §calendar
MONTHS = ["Frostmere", "Thawing", "Sowmonth", "Greenwake", "Blossomtide", "Highsun", "Goldfall", "Harvestmoon",
          "Emberfall", "Mistmonth", "Duskwane", "Deepwinter"]


def campaign_entry(campaign: int, episode_in_campaign: int) -> tuple[dict, dict]:
    camp = load_json(CAMPAIGN_DIR / f"c{campaign:02d}.json")
    ep = next(e for e in camp["episodes"] if e["episode"] == episode_in_campaign)
    return camp, ep


def previous_summaries(n: int = 3, before: str | None = None) -> list[dict]:
    """The last ``n`` episode summaries from the episode archive (``episodes/<id>/wiki_facts.json``)."""
    from .wiki import load_archive
    eps = [e for e in load_archive() if before is None or e["id"] < before]
    return [{"episode": e["id"], "title": e["record"].get("title"), "summary": e["facts"]["summary"]}
            for e in eps[-n:] if e.get("facts")]


def canon_pages(tags: list[str], before: str | None = None) -> list[dict]:
    """Accumulated canon (what has been shown on screen) for the episode's tags."""
    from .wiki import build_canon, load_archive
    canon = build_canon([e for e in load_archive() if before is None or e["id"] < before])
    return [canon[t] for t in tags if t in canon]


def available_maps() -> dict[str, dict]:
    out = {}
    for p in sorted((ROOT / "assets" / "maps").glob("*.json")):
        d = load_json(p)
        out[d["id"]] = {"name": d.get("name", d["id"]), "size": d["size"], "points": d.get("points", {}),
                        "props": [{"id": x.get("id"), "prop": x["prop"], "at": x["at"]} for x in d.get("props", [])
                                  if x.get("id")]}
    return out


def available_sprites() -> list[str]:
    return sorted(load_json(ROOT / "assets" / "manifest.json")["actors"])


@dataclass
class ContextPack:
    """Everything the steps of one episode need, built once."""
    episode_id: str
    campaign: dict
    entry: dict
    sheets: dict
    world: dict
    dm_core: str
    public_core: str

    @classmethod
    def build(cls, campaign: int, episode_in_campaign: int, sheets: dict, world: dict) -> "ContextPack":
        camp, entry = campaign_entry(campaign, episode_in_campaign)
        dm = "\n\n".join([
            "# SERIES BIBLE (DM copy: contains SECRET blocks - foreshadow, never reveal before the listed episode)",
            bible_text(DM_CORE, public=False),
            "# PARTY DOSSIERS (DM copy)",
            dossier_text(public=False),
        ])
        public = "\n\n".join([
            "# SERIES BIBLE (public copy: no secrets)",
            bible_text(PUBLIC_CORE, public=True),
            "# PARTY (public)",
            dossier_text(public=True),
        ])
        eid = f"C{campaign:02d}-E{episode_in_campaign:03d}"
        return cls(eid, camp, entry, sheets, world, dm, public)

    # Per-episode, uncached material ------------------------------------
    def campaign_view(self) -> str:
        eps = self.campaign["episodes"]
        n = self.entry["episode"]
        near = [e for e in eps if n - 2 <= e["episode"] <= n + 3]
        return json.dumps({"campaign": {k: v for k, v in self.campaign.items() if k != "episodes"},
                           "this_episode": self.entry,
                           "nearby_episodes": [{k: e[k] for k in ("episode", "title", "beat")} for e in near
                                               if e["episode"] != n]}, ensure_ascii=False, indent=1)

    def state_view(self, public: bool = False) -> str:
        camps = features.enabled("camps", self.episode_id)
        party = party_brief(self.sheets, progress=features.enabled("level_ups", self.episode_id), supplies=camps)
        if camps:
            shared = sum(i["qty"] for i in self.world["party"].get("shared_inventory", []) if i["id"] == "rations")
            party += f"\n- shared packs: {shared} rations"
        return "## Party\n" + party + "\n\n## World\n" + world_brief(self.world, public)

    def memories(self) -> str:
        """What each party member has lived through (pqc/pipeline/memories.py), for callbacks."""
        if not features.enabled("memories", self.episode_id):
            return ""
        from . import memories
        from .wiki import load_archive
        names = {cid: s["name"].split()[0] for cid, s in self.sheets.items()}
        return memories.as_text(memories.collect(load_archive(), self.world, before=self.episode_id), names)

    def recap(self) -> str:
        prev = previous_summaries(3, before=self.episode_id)
        canon = canon_pages(self.entry.get("tags", []), before=self.episode_id)
        return json.dumps({"previous_episodes": prev, "canon_for_tags": canon}, ensure_ascii=False, indent=1)

    def stage_view(self) -> str:
        maps = {m: available_maps()[m] for m in self.entry.get("maps", []) if m in available_maps()}
        return json.dumps({"maps": maps, "sprites": available_sprites(),
                           "monsters": sorted(_monster_ids()), "skills": sorted(SKILLS)}, ensure_ascii=False)


def _monster_ids() -> list[str]:
    from .. import data
    return list(data.monsters())


# ------------------------------------------------------------------ spoilers
def spoiler_hits(text: str, campaign: int) -> list[dict]:
    """Phrases from ``bible/spoilers.json`` whose reveal campaign is still ahead."""
    terms = load_json(BIBLE / "spoilers.json")["terms"]
    low = text.lower()
    return [t for t in terms if t["reveal_campaign"] > campaign and t["phrase"].lower() in low]
