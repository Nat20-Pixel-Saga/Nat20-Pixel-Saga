#!/usr/bin/env python3
"""Render committed episodes and publish them as GitHub releases on their premiere.

Runs in GitHub Actions (.github/workflows/release.yml) after each push and
twice every evening. The renderer is deterministic, so the MP4 is rebuilt on
the runner from the committed timeline instead of being stored in git; the
common intro and outro (scripts/branding.py) are added in the same encode.

Every episode follows the premiere schedule (production/schedule.json, see
pqc/schedule.py): until its premiere the release is a *draft* (visible only to
the repository's owners, who can still download the video to upload it by hand),
and from the premiere on it is public. A video is re-rendered whenever its
timeline, thumbnail or the intro/outro change.

    python scripts/release_episodes.py          # sync visibility, then render what's needed
    python scripts/release_episodes.py --plan   # only print how many need rendering (render=<n>)

Needs `gh` with GH_TOKEN (and, for rendering, ffmpeg and the assets in vendor/).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc import schedule  # noqa: E402

MARK = "timeline sha256: "
BUMPER_SOURCES = [ROOT / "scripts" / "branding.py", ROOT / "pqc" / "render" / "brand.py"]


def repo() -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    return json.loads((ROOT / "wiki" / "data" / "site.json").read_text())["repo"]


def gh_api(path: str, method: str = "GET", fields: dict | None = None):
    cmd = ["gh", "api", "-X", method, path]
    for k, v in (fields or {}).items():
        cmd += ["-F", f"{k}={json.dumps(v)}"] if isinstance(v, bool) else ["-f", f"{k}={v}"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else None


def all_releases(r: str) -> dict[str, dict]:
    """tag -> release, drafts included (needs push access)."""
    out, page = {}, 1
    while True:
        batch = gh_api(f"repos/{r}/releases?per_page=100&page={page}")
        if not batch:
            return out
        for rel in batch:
            out.setdefault(rel["tag_name"], rel)
        page += 1


def committed_episodes() -> list[Path]:
    world = json.loads((ROOT / "state" / "world.json").read_text())
    reached = (world["series"]["campaign"], world["series"]["episode_in_campaign"])
    out = []
    for d in sorted((ROOT / "episodes").glob("C??-E???")):
        camp, ep = int(d.name[1:3]), int(d.name[-3:])
        if (camp, ep) <= reached and (d / "timeline.json").exists() and (d / "packaging.json").exists():
            out.append(d)
    return out


def digest(d: Path) -> str:
    h = hashlib.sha256()
    for p in [d / "timeline.json", d / "thumbnail.png", *BUMPER_SOURCES]:
        h.update(p.read_bytes())
    return h.hexdigest()


def rendered_digest(rel: dict) -> str:
    for line in (rel.get("body") or "").splitlines():
        if MARK in line:
            return line.split(MARK, 1)[1].split()[0]
    return ""


def notes(d: Path, dig: str) -> str:
    pk = json.loads((d / "packaging.json").read_text())
    body = pk.get("description_full", pk["description"])
    t = schedule.premiere(d.name)
    if t:
        body = f"Premiere: {schedule.local_label(t)}\n\n" + body
    return body + f"\n\n<!-- {MARK}{dig} -->\n"


def sync_visibility(r: str, rels: dict[str, dict], now: dt.datetime) -> None:
    """Drafts until the premiere, public from then on (fast; no rendering)."""
    for tag, rel in sorted(rels.items()):
        if not (tag.startswith("C") and "-E" in tag):
            continue
        public = schedule.is_public(tag, now)
        if rel["draft"] and public:
            gh_api(f"repos/{r}/releases/{rel['id']}", "PATCH", {"draft": False})
            print(f"{tag}: premiered, release published", flush=True)
        elif not rel["draft"] and not public:
            gh_api(f"repos/{r}/releases/{rel['id']}", "PATCH", {"draft": True})
            print(f"{tag}: premieres {schedule.premiere(tag).isoformat()}, release hidden until then", flush=True)


def to_render(rels: dict[str, dict]) -> list[Path]:
    return [d for d in committed_episodes()
            if d.name not in rels or rendered_digest(rels[d.name]) != digest(d)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()
    r = repo()
    now = dt.datetime.now(dt.timezone.utc)
    rels = all_releases(r)
    todo = to_render(rels)
    if a.plan:
        sync_visibility(r, rels, now)
        print(f"render={len(todo)}: {' '.join(d.name for d in todo) or '-'}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                fh.write(f"render={len(todo)}\n")
        return 0
    sync_visibility(r, rels, now)
    if not todo:
        print("0 episode(s) to render")
        return 0

    from pqc.render.assets import Assets
    from pqc.render.video import render
    assets = Assets()
    spec = importlib.util.spec_from_file_location("branding", ROOT / "scripts" / "branding.py")
    branding = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(branding)
    intro, outro = branding.bumpers(assets)

    for d in todo:
        eid = d.name
        tl = json.loads((d / "timeline.json").read_text())
        pk = json.loads((d / "packaging.json").read_text())
        dig = digest(d)
        video = d / f"{eid}.mp4"
        thumb = d / f"{eid}-thumbnail.png"
        notes_file = d / "release_notes.md"
        print(f"rendering {eid} ...", flush=True)
        render(tl, video, assets, scale=4, preset="medium", pre=intro, post=outro, log=lambda *_: None)
        thumb.write_bytes((d / "thumbnail.png").read_bytes())
        notes_file.write_text(notes(d, dig))
        public = schedule.is_public(eid)
        rel = rels.get(eid)
        if rel is None:
            cmd = ["gh", "release", "create", eid, str(video), str(thumb), "--title", pk["title"],
                   "--notes-file", str(notes_file)]
            if not public:
                cmd.append("--draft")
            subprocess.run(cmd, check=True)
        else:
            subprocess.run(["gh", "release", "upload", eid, str(video), str(thumb), "--clobber"], check=True)
            gh_api(f"repos/{r}/releases/{rel['id']}", "PATCH",
                   {"name": pk["title"], "body": notes_file.read_text(), "draft": not public})
        for f in (video, thumb, notes_file):
            f.unlink()
        print(f"{eid}: {'released' if public else 'ready as a draft until ' + schedule.premiere(eid).isoformat()}",
              flush=True)
    print(f"{len(todo)} episode(s) rendered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
