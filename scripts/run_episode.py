#!/usr/bin/env python3
"""Produce one episode: plan, dice, script, continuity, timeline, video, wiki, packaging.

    python scripts/run_episode.py 1                      # offline: replay fixtures/C01-E001, no render
    python scripts/run_episode.py 1 --render preview     # + 960x540 MP4 (quick)
    python scripts/run_episode.py 1 --render full        # + 1080p MP4
    python scripts/run_episode.py 2 --live --commit      # real Claude calls (needs ANTHROPIC_API_KEY),
                                                         # then update state/ and rebuild wiki/docs
    python scripts/run_episode.py 2 --record             # live, and save the outputs as fixtures
    python scripts/run_episode.py 2 --agent              # a Claude session writes each step itself:
                                                         # exit code 3 = read episodes/<id>/pending/<step>.md,
                                                         # write fixtures/<id>/<step>.json, run again

Outputs go to episodes/<id>/ (plan, outcomes, script, continuity, timeline,
chapters, wiki facts, packaging, thumbnail, cost, state_after, video).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc.pipeline.episode import EpisodeConfig, EpisodeError, NeedsAuthor, run_episode  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode", type=int, help="episode number within the campaign")
    ap.add_argument("--campaign", type=int, default=1)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="call the Claude API")
    mode.add_argument("--record", action="store_true", help="call the API and save outputs as fixtures")
    mode.add_argument("--agent", action="store_true", help="this Claude session writes each step (see above)")
    ap.add_argument("--render", choices=["none", "preview", "full"], default="none")
    ap.add_argument("--commit", action="store_true", help="write the new state and rebuild the wiki")
    ap.add_argument("--no-batch", action="store_true", help="live calls at standard (not Batch API) prices")
    ap.add_argument("--attempt", type=int, default=1, help="only after a logged technical failure (bible 10 §2)")
    ap.add_argument("--wiki-url", default=None, help="e.g. https://nat20pixelsaga.com")
    ap.add_argument("--state-dir", default=None, help="state to start from (default: the episode's archived "
                                                       "state_before, else state/)")
    args = ap.parse_args()
    cfg = EpisodeConfig(campaign=args.campaign, episode=args.episode,
                        mode="live" if args.live else "record" if args.record else "agent" if args.agent else "offline",
                        render=args.render, commit=args.commit, batch=not args.no_batch, attempt=args.attempt,
                        wiki_url=args.wiki_url, state_dir=Path(args.state_dir).resolve() if args.state_dir else None)
    try:
        out = run_episode(cfg)
    except NeedsAuthor as need:
        print(f"NEEDS {need.step}: read {need.prompt_path} and write {need.fixture_path}, then run again.")
        return 3
    except EpisodeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"id": out["id"], "minutes": round(out["duration"] / 60, 2), "cost_usd": out["cost"]["total_usd"],
                      "video": str(out["video"]) if out["video"] else None}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
