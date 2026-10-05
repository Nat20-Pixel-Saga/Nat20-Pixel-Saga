#!/usr/bin/env python3
"""Render any timeline JSON to MP4.

    python scripts/render_timeline.py assets/timelines/gate_test_scene.json out.mp4 [--scale 4] [--stills 5,10]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc.render.video import render  # noqa: E402
from pqc.schema import validate_named  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("out")
    ap.add_argument("--scale", type=int, default=4, help="4 = 1920x1080, 2 = 960x540 preview")
    ap.add_argument("--stills", default="", help="comma-separated seconds to save as PNG")
    ap.add_argument("--preset", default="medium")
    args = ap.parse_args()
    tl = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
    errors = validate_named(tl, "timeline")
    if errors:
        print("Timeline invalid:\n  " + "\n  ".join(errors[:20]))
        return 2
    stills = [float(s) for s in args.stills.split(",") if s.strip()]
    render(tl, args.out, scale=args.scale, preset=args.preset, stills=stills,
           stills_dir=Path(args.out).with_suffix("").parent / "stills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
