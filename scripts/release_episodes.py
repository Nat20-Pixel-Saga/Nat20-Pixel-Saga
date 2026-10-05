#!/usr/bin/env python3
"""Render and publish every committed episode that has no GitHub release yet, and
re-render any whose timeline changed since its video was made.

Runs in GitHub Actions (.github/workflows/release.yml) after each push: the
renderer is deterministic, so the MP4 is rebuilt on the runner from the
committed timeline instead of being stored in git. Needs `gh` with GH_TOKEN.

An episode is released only once it is committed to the story (the live state
in state/world.json has reached it), never from work in progress.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


MARK = "timeline sha256: "


def release_state(tag: str) -> str | None:
    """None if there is no release; otherwise the timeline hash its video was rendered from ('' if unknown)."""
    r = subprocess.run(["gh", "release", "view", tag, "--json", "body", "-q", ".body"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if MARK in line:
            return line.split(MARK, 1)[1].split()[0]
    return ""


def main() -> int:
    from pqc.render.video import render
    world = json.loads((ROOT / "state" / "world.json").read_text())
    reached = (world["series"]["campaign"], world["series"]["episode_in_campaign"])
    done = 0
    for d in sorted((ROOT / "episodes").glob("C??-E???")):
        eid = d.name
        camp, ep = int(eid[1:3]), int(eid[-3:])
        if (camp, ep) > reached or not (d / "timeline.json").exists() or not (d / "packaging.json").exists():
            continue
        digest = hashlib.sha256((d / "timeline.json").read_bytes() + (d / "thumbnail.png").read_bytes()).hexdigest()
        have = release_state(eid)
        if have == digest:
            continue
        tl = json.loads((d / "timeline.json").read_text())
        pk = json.loads((d / "packaging.json").read_text())
        video = d / f"{eid}.mp4"
        print(f"rendering {eid} ...", flush=True)
        render(tl, video, scale=4, preset="medium", log=lambda *_: None)
        thumb = d / f"{eid}-thumbnail.png"
        thumb.write_bytes((d / "thumbnail.png").read_bytes())
        notes = d / "release_notes.md"
        notes.write_text(pk.get("description_full", pk["description"]) + f"\n\n<!-- {MARK}{digest} -->\n")
        if have is None:
            subprocess.run(["gh", "release", "create", eid, str(video), str(thumb), "--title", pk["title"],
                            "--notes-file", str(notes)], check=True)
        else:                       # the episode's timeline changed (e.g. a renamed title card): replace the video
            subprocess.run(["gh", "release", "upload", eid, str(video), str(thumb), "--clobber"], check=True)
            subprocess.run(["gh", "release", "edit", eid, "--title", pk["title"], "--notes-file", str(notes)],
                           check=True)
        for f in (video, thumb, notes):
            f.unlink()
        done += 1
        print(f"released {eid}", flush=True)
    print(f"{done} episode(s) released")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
