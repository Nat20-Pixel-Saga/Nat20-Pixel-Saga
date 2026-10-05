"""The premiere schedule: when each episode goes public.

One rule drives the YouTube premiere, the wiki and the GitHub release, so an
episode appears everywhere at the same moment (production/schedule.json):
episodes premiere in order, one per allowed weekday at a fixed local time.
"""
from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from .state import ROOT

CONFIG = ROOT / "production" / "schedule.json"
EPISODES_PER_CAMPAIGN_DEFAULT = 40


@lru_cache(maxsize=1)
def _config_cached(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text())


def config() -> dict:
    return _config_cached(str(CONFIG), CONFIG.stat().st_mtime)


def _campaign_length(c: int) -> int:
    f = ROOT / "campaign" / f"c{c:02d}.json"
    if f.exists():
        return len(json.loads(f.read_text()).get("episodes", [])) or EPISODES_PER_CAMPAIGN_DEFAULT
    return EPISODES_PER_CAMPAIGN_DEFAULT


def ordinal(eid: str) -> int:
    """Position of an episode in the whole series (C01-E001 = 0)."""
    c, n = int(eid[1:3]), int(eid[-3:])
    return sum(_campaign_length(k) for k in range(1, c)) + n - 1


def premiere(eid: str, cfg: dict | None = None) -> dt.datetime | None:
    """When `eid` goes public (aware, UTC); None if it comes before the first scheduled episode."""
    cfg = cfg or config()
    tz = ZoneInfo(cfg["timezone"])
    if eid in cfg.get("overrides", {}):
        local = dt.datetime.strptime(cfg["overrides"][eid], "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        return local.astimezone(dt.timezone.utc)
    k = ordinal(eid) - ordinal(cfg["first_episode"])
    if k < 0:
        return None
    hh, mm = (int(x) for x in cfg["time"].split(":"))
    days = set(cfg["weekdays"])
    skip = set(cfg.get("skip_dates", []))
    day = dt.date.fromisoformat(cfg["first_date"])
    seen = -1
    while True:
        if day.weekday() in days and day.isoformat() not in skip:
            seen += 1
            if seen == k:
                return dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz).astimezone(dt.timezone.utc)
        day += dt.timedelta(days=1)


def is_public(eid: str, now: dt.datetime | None = None, cfg: dict | None = None) -> bool:
    now = now or dt.datetime.now(dt.timezone.utc)
    t = premiere(eid, cfg)
    return t is None or t <= now


def local_label(t: dt.datetime, cfg: dict | None = None) -> str:
    """'Monday 12 October 2026, 21:00 (Paris time)'."""
    cfg = cfg or config()
    tz = cfg["timezone"]
    loc = t.astimezone(ZoneInfo(tz))
    city = tz.split("/")[-1].replace("_", " ")
    return f"{loc.strftime('%A')} {loc.day} {loc.strftime('%B %Y')}, {loc.strftime('%H:%M')} ({city} time)"
