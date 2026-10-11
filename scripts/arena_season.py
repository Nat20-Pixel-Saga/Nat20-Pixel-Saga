#!/usr/bin/env python3
"""The Pit: simulate and render a season of arena episodes, their Shorts and thumbnails.

    python scripts/arena_season.py all 1                  # episode 1: video, Shorts, thumbnail, log
    python scripts/arena_season.py all 1-10               # the whole season
    python scripts/arena_season.py video 3 --preview      # quick 960x540 check with fewer simulations
    python scripts/arena_season.py meta                   # titles, descriptions, calendar (production/arena/)

Outputs go to render_out/arena/<season>/E01/ ... (set with --out). Simulations are
cached there as result.json, so re-rendering never re-simulates.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc.arena import produce as P  # noqa: E402
from pqc.arena import season as SE  # noqa: E402
from pqc.render.assets import Assets  # noqa: E402


def episodes_arg(s: str, season: dict) -> list[int]:
    if s == "all":
        return [e["n"] for e in season["episodes"]]
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def results_upto(season, n, arena, cache, full_n=True):
    res = {}
    for e in season["episodes"]:
        if e["n"] < n:
            res[e["n"]] = SE.resolve(season, e["n"], arena, cache, full=False)
    res[n] = SE.resolve(season, n, arena, cache, full=full_n)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["sim", "video", "shorts", "thumb", "all", "meta", "plan"])
    ap.add_argument("episodes", nargs="?", default="all")
    ap.add_argument("--season", default=str(ROOT / "production" / "arena" / "s1.json"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--preview", action="store_true", help="960x540, fewer simulations, fast encode")
    ap.add_argument("--stills", action="store_true")
    args = ap.parse_args()
    season = SE.load(args.season)
    out_root = Path(args.out or ROOT / "render_out" / "arena" / season["id"])
    if args.preview:
        season["quality"] = {"samples": 40, "samples_multi": 24, "prior": 400, "prior_multi": 200, "crown_n": 150}
        out_root = out_root.parent / (out_root.name + "-preview")
    cache = out_root
    assets = Assets()
    arena = SE.Arena(assets)
    if args.what == "meta":
        from pqc.arena import meta
        meta.write_all(season, out_root, assets, arena)
        return 0
    for n in episodes_arg(args.episodes, season):
        t0 = time.time()
        d = out_root / f"E{n:02d}"
        d.mkdir(parents=True, exist_ok=True)
        res = results_upto(season, n, arena, cache)
        print(f"E{n:02d} simulated in {time.time() - t0:.0f}s", flush=True)
        if args.what == "sim":
            continue
        tl = SE.episode_timeline(season, n, res, assets)
        stem = f"pit-s1e{n:02d}"
        (d / f"{stem}.timeline.json").write_text(json.dumps(tl, ensure_ascii=False))
        (d / f"{stem}.rolls.json").write_text(json.dumps(P.roll_log(season, n, res[n]), ensure_ascii=False))
        times, total = P.dry_run(tl, assets)
        ch = P.chapters(tl, times)
        (d / f"{stem}.chapters.txt").write_text("\n".join(f"{P.fmt_t(t)} {l}" for t, l in ch) + "\n")
        marks = {"duration_s": round(total, 2), "chapters": [[round(t, 2), l] for t, l in ch]}
        (d / f"{stem}.marks.json").write_text(json.dumps(marks))
        if args.what in ("video", "all"):
            stills = None
            if args.stills or args.preview:
                stills = [round(t + 1.2, 2) for t, c in zip(times, tl["cues"])
                          if c["op"] in ("show_card", "show_bout", "show_ko")][:40]
                stills += [round(t + 1.1, 2) for t, c in zip(times, tl["cues"]) if c["op"] == "show_attack"][::6][:20]
            scale, preset, crf = (2, "veryfast", 23) if args.preview else (4, "medium", 18)
            info = P.render_episode(tl, d / f"{stem}.mp4", assets, scale, stills, preset, crf)
            print(json.dumps({k: v for k, v in info.items() if k != "stills"}), flush=True)
        if args.what in ("shorts", "all"):
            from pqc.arena import vertical
            infos = vertical.render_shorts(season, n, res, tl, times, d, assets, preview=args.preview)
            for info in infos:
                print(json.dumps(info), flush=True)
            (d / "shorts.json").write_text(json.dumps(dict(zip(("trailer", "a", "b"), infos))))
        if args.what in ("thumb", "all"):
            from pqc.arena import thumbs
            print(thumbs.render(season, n, res, d / f"{stem}-thumbnail.png", assets), flush=True)
        print(f"E{n:02d} done in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
