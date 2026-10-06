"""Show updates that start at a given episode (``production/features.json``).

Episodes already made are never regenerated, but they are replayed (tests, audits)
and must come out exactly as they were. Every behaviour change to the engine or the
pipeline is therefore switched on per episode: ``enabled("tactics_v2", "C01-E011")``.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "production" / "features.json"
EID = re.compile(r"^C(\d\d)-E(\d\d\d)$")


def _key(eid: str) -> tuple[int, int]:
    m = EID.match(eid or "")
    if not m:
        raise ValueError(f"Not an episode id: {eid!r}")
    return int(m.group(1)), int(m.group(2))


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    if not FILE.exists():
        return {}
    return {k: v for k, v in json.loads(FILE.read_text()).items() if k != "description"}


def enabled(name: str, episode_id: str) -> bool:
    """True if ``name`` applies to ``episode_id`` (unknown features are off)."""
    start = _table().get(name)
    return bool(start) and _key(episode_id) >= _key(start)


def first_episode(name: str) -> str | None:
    return _table().get(name)
