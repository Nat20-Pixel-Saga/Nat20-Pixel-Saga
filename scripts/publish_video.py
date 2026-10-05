#!/usr/bin/env python3
"""Attach an episode's video and thumbnail to a GitHub release (one release per
episode, tag = episode id) and record the link in its packaging, so the wiki's
episode page shows "Watch". Videos stay out of git history.

    python scripts/publish_video.py C01-E001 [--repo OWNER/NAME]     # or just: 1 (Campaign 1)

Uses the GitHub REST API through curl (credentials come from the environment:
GH_TOKEN/GITHUB_TOKEN if set, otherwise the session's git proxy).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DEFAULT_REPO = "Nat20-Pixel-Saga/Nat20-Pixel-Saga"


def api(method: str, url: str, data: dict | None = None, upload: Path | None = None, ctype: str | None = None):
    cmd = ["curl", "-sS", "-X", method, url, "-H", "Accept: application/vnd.github+json"]
    token = os.environ.get("PQC_GITHUB_TOKEN")
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    if upload is not None:
        cmd += ["-H", f"Content-Type: {ctype}", "--data-binary", f"@{upload}"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else {}


def publish(eid: str, repo: str) -> str:
    d = ROOT / "episodes" / eid
    pk = json.loads((d / "packaging.json").read_text())
    base = f"https://api.github.com/repos/{repo}"
    rel = api("GET", f"{base}/releases/tags/{eid}")
    if "id" not in rel:
        rel = api("POST", f"{base}/releases", {
            "tag_name": eid, "name": pk["title"], "body": pk.get("description_full", pk["description"]),
            "draft": False, "prerelease": False})
        if "id" not in rel:
            raise SystemExit(f"Could not create release: {rel}")
    have = {a["name"]: a for a in rel.get("assets", [])}
    up = f"https://uploads.github.com/repos/{repo}/releases/{rel['id']}/assets"
    names = {"video.mp4": f"{eid}.mp4", "thumbnail.png": f"{eid}-thumbnail.png"}
    for local, name in names.items():
        if name in have:
            api("DELETE", f"{base}/releases/assets/{have[name]['id']}")
        ctype = "video/mp4" if local.endswith(".mp4") else "image/png"
        asset = api("POST", f"{up}?name={name}", upload=d / local, ctype=ctype)
        if "browser_download_url" not in asset:
            raise SystemExit(f"Upload of {name} failed: {asset}")
        if local == "video.mp4":
            pk["video_url"] = asset["browser_download_url"]
    pk["release_url"] = rel.get("html_url")
    (d / "packaging.json").write_text(json.dumps(pk, indent=2, ensure_ascii=False) + "\n")
    return pk["video_url"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("episode")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    a = ap.parse_args()
    eid = f"C01-E{int(a.episode):03d}" if a.episode.isdigit() else a.episode
    print(publish(eid, a.repo))
